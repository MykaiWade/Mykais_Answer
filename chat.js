/*
 * - Filters public question rooms by badge and manages chat history, live messages, and calls.
 * - Connects chat.html to profile.js and server.py's question, chat, and WebSocket endpoints.
*/
(function () {
    var topic = document.getElementById("topic");
    var messages = document.getElementById("messages");
    var chatStatus = document.getElementById("chatStatus");
    var sendForm = document.getElementById("sendRow");
    var textInput = document.getElementById("text");
    var sendButton = sendForm.querySelector("button[type='submit']");
    var chatList = document.getElementById("chatList");
    var chatListStatus = document.getElementById("chatListStatus");
    // These controls filter only public questions; private match chats remain in their own list.
    var questionSearch = document.getElementById("questionSearch");
    var questionDirectory = document.getElementById("questionDirectory");
    var questionDirectoryStatus = document.getElementById("questionDirectoryStatus");
    var questionBadgePicker = window.BadgePicker.mount(
        document.getElementById("questionBadgeFilter")
    );
    var publicQuestions = [];
    var callSection = document.getElementById("callSection");
    var callStatus = document.getElementById("callStatus");
    var joinCallButton = document.getElementById("joinCallButton");
    var joinAudioButton = document.getElementById("joinAudioButton");
    var muteCallButton = document.getElementById("muteCallButton");
    var cameraCallButton = document.getElementById("cameraCallButton");
    // Finds the control used to start or stop sharing a screen.
    var shareScreenButton = document.getElementById("shareScreenButton");
    var leaveCallButton = document.getElementById("leaveCallButton");
    var callVideos = document.getElementById("callVideos");
    var localVideo = document.getElementById("localVideo");
    var remoteVideos = document.getElementById("remoteVideos");
    var room = new URLSearchParams(window.location.search).get("room");
    var hasValidRoom = room && /^(?:\d+-\d+|question-\d+)$/.test(room); // Accepts legacy pair rooms and public question rooms.
    var socket = null;
    var callStream = null;
    // Keeps a separate screen stream so it can replace the camera video track.
    var screenStream = null;
    var callParticipantId = null;
    var callPeers = Object.create(null);

    function showMessage(message) {
        chatStatus.textContent = message;
    }

    function showCallStatus(message) {
        callStatus.textContent = message;
    }

    /* Use a small WebRTC mesh for this prototype; the server only relays setup data. */
    function sendCallSignal(target, signal) {
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({
                type: "call-signal",
                target: target,
                signal: signal
            }));
        }
    }

    function updateCallStatus() {
        var count = Object.keys(callPeers).length + 1;
        showCallStatus(count + (count === 1 ? " person" : " people")
            + " in the call. Share this chat room so others can join.");
    }

    function removeCallPeer(participantId) {
        var peer = callPeers[participantId];
        if (!peer) {
            return;
        }
        peer.connection.close();
        peer.tile.remove();
        delete callPeers[participantId];
        updateCallStatus();
    }

    function createCallPeer(participantId, realName, shouldOffer) {
        if (callPeers[participantId]) {
            return callPeers[participantId];
        }

        var tile = document.createElement("div");
        tile.className = "call-video";
        var video = document.createElement("video");
        video.autoplay = true;
        video.playsInline = true;
        var name = document.createElement("span");
        name.textContent = realName || "Chat participant";
        tile.appendChild(video);
        tile.appendChild(name);
        remoteVideos.appendChild(tile);

        var connection = new RTCPeerConnection({
            iceServers: [{ urls: "stun:stun.l.google.com:19302" }]
        });
        var peer = {
            connection: connection,
            tile: tile,
            pendingCandidates: []
        };
        callPeers[participantId] = peer;

        // Audio always comes from the call's microphone, not the screen capture.
        callStream.getAudioTracks().forEach(function (track) {
            connection.addTrack(track, callStream);
        });
        // Sends screen video when it is active, otherwise sends the camera.
        var videoTrack = screenStream
            ? screenStream.getVideoTracks()[0]
            : callStream.getVideoTracks()[0];
        if (videoTrack) {
            connection.addTrack(videoTrack, screenStream || callStream);
        }
        connection.ontrack = function (event) {
            if (event.streams[0]) {
                video.srcObject = event.streams[0];
            }
        };
        connection.onicecandidate = function (event) {
            if (event.candidate) {
                sendCallSignal(participantId, {
                    type: "candidate",
                    candidate: event.candidate
                });
            }
        };
        connection.onconnectionstatechange = function () {
            if (connection.connectionState === "failed") {
                showCallStatus("A peer connection failed. A TURN relay may be needed on this network.");
            }
        };
        if (shouldOffer) {
            connection.createOffer()
                .then(function (offer) {
                    return connection.setLocalDescription(offer);
                })
                .then(function () {
                    sendCallSignal(participantId, {
                        type: "description",
                        description: connection.localDescription
                    });
                })
                .catch(function (error) {
                    showCallStatus("Could not start the call connection: " + error.message);
                });
        }
        return peer;
    }

    function addPendingCandidates(peer) {
        var candidates = peer.pendingCandidates.splice(0);
        return candidates.reduce(function (chain, candidate) {
            return chain.then(function () {
                return peer.connection.addIceCandidate(new RTCIceCandidate(candidate));
            });
        }, Promise.resolve());
    }

    function handleCallSignal(data) {
        var peer = callPeers[data.participant_id]
            || createCallPeer(data.participant_id, "Chat participant", false);
        var signal = data.signal;
        if (signal.type === "description") {
            peer.connection.setRemoteDescription(signal.description)
                .then(function () {
                    return addPendingCandidates(peer);
                })
                .then(function () {
                    if (signal.description.type !== "offer") {
                        return;
                    }
                    return peer.connection.createAnswer()
                        .then(function (answer) {
                            return peer.connection.setLocalDescription(answer);
                        })
                        .then(function () {
                            sendCallSignal(data.participant_id, {
                                type: "description",
                                description: peer.connection.localDescription
                            });
                        });
                })
                .catch(function (error) {
                    showCallStatus("Could not set up the call: " + error.message);
                });
        } else if (signal.type === "candidate") {
            if (peer.connection.remoteDescription) {
                peer.connection.addIceCandidate(new RTCIceCandidate(signal.candidate))
                    .catch(function (error) {
                        showCallStatus("Could not connect to a call participant: " + error.message);
                    });
            } else {
                peer.pendingCandidates.push(signal.candidate);
            }
        }
    }

    function resetCall(sendLeave) {
        if (sendLeave && callParticipantId && socket
                && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: "call-leave" }));
        }
        callParticipantId = null;
        Object.keys(callPeers).forEach(removeCallPeer);
        // Stop the browser's screen capture before the call is fully reset.
        if (screenStream) {
            screenStream.getTracks().forEach(function (track) {
                track.stop();
            });
            screenStream = null;
        }
        if (callStream) {
            callStream.getTracks().forEach(function (track) {
                track.stop();
            });
            callStream = null;
        }
        localVideo.srcObject = null;
        localVideo.classList.remove("sharing-screen");
        remoteVideos.innerHTML = "";
        callVideos.hidden = true;
        joinCallButton.hidden = false;
        joinAudioButton.hidden = false;
        joinCallButton.disabled = !socket || socket.readyState !== WebSocket.OPEN;
        joinAudioButton.disabled = joinCallButton.disabled;
        muteCallButton.disabled = true;
        cameraCallButton.disabled = true;
        // Restore the screen-sharing control to its idle state.
        shareScreenButton.disabled = true;
        shareScreenButton.textContent = "Share screen";
        leaveCallButton.hidden = true;
    }

    function joinCall(audioOnly) {
        if (!window.SiteProfile.current()) {
            showCallStatus("Sign in before joining a call.");
            return;
        }
        if (!socket || socket.readyState !== WebSocket.OPEN || callParticipantId) {
            showCallStatus("Wait for the chat connection before joining a call.");
            return;
        }
        if (window.isSecureContext === false) {
            showCallStatus("Camera and microphone access requires HTTPS (or localhost).");
            return;
        }
        if (!navigator.mediaDevices
                || typeof navigator.mediaDevices.getUserMedia !== "function") {
            showCallStatus(
                "This browser does not provide camera and microphone access. "
                + "Open the site in Safari or Chrome instead of an in-app browser, "
                + "and make sure the browser is up to date."
            );
            return;
        }
        if (typeof RTCPeerConnection !== "function") {
            showCallStatus("This browser does not support WebRTC calls.");
            return;
        }

        joinCallButton.disabled = true;
        joinAudioButton.disabled = true;
        showCallStatus("Requesting camera and microphone permission...");
        var connection = socket;
        navigator.mediaDevices.getUserMedia({
            audio: true,
            video: !audioOnly
        }).then(function (stream) {
            if (socket !== connection || connection.readyState !== WebSocket.OPEN
                    || !window.SiteProfile.current()) {
                stream.getTracks().forEach(function (track) {
                    track.stop();
                });
                return;
            }
            callStream = stream;
            localVideo.srcObject = stream;
            callVideos.hidden = false;
            connection.send(JSON.stringify({ type: "call-join" }));
            showCallStatus("Joining the call...");
        }).catch(function (error) {
            if (socket === connection) {
                resetCall(false);
                showCallStatus("Could not access your camera or microphone: " + error.message);
            }
        });
    }

    joinCallButton.addEventListener("click", function () {
        joinCall(false);
    });
    joinAudioButton.addEventListener("click", function () {
        joinCall(true);
    });
    leaveCallButton.addEventListener("click", function () {
        resetCall(true);
        showCallStatus("You left the call.");
    });
    muteCallButton.addEventListener("click", function () {
        if (!callStream) {
            return;
        }
        var audioTracks = callStream.getAudioTracks();
        var enabled = audioTracks.some(function (track) {
            return track.enabled;
        });
        audioTracks.forEach(function (track) {
            track.enabled = !enabled;
        });
        muteCallButton.textContent = enabled ? "Unmute microphone" : "Mute microphone";
    });
    cameraCallButton.addEventListener("click", function () {
        if (!callStream) {
            return;
        }
        var videoTracks = callStream.getVideoTracks();
        // Camera controls stay disabled while screen video is taking the video track.
        if (screenStream) {
            return;
        }
        var enabled = videoTracks.some(function (track) {
            return track.enabled;
        });
        videoTracks.forEach(function (track) {
            track.enabled = !enabled;
        });
        cameraCallButton.textContent = enabled ? "Turn camera on" : "Turn camera off";
    });

    // Stops a display capture and sends the camera track back to every peer.
    function stopScreenShare() {
        if (!screenStream) {
            return;
        }
        // Stop the browser capture and remove the active screen stream reference.
        var screenTrack = screenStream.getVideoTracks()[0];
        screenStream = null;
        if (screenTrack) {
            screenTrack.stop();
        }

        // Replace the shared screen with the camera, if the user joined with one.
        var cameraTrack = callStream ? callStream.getVideoTracks()[0] : null;
        Object.keys(callPeers).forEach(function (participantId) {
            var senders = callPeers[participantId].connection.getSenders();
            senders.forEach(function (sender) {
                if (sender.track && sender.track.kind === "video") {
                    // replaceTrack swaps video without recreating the whole peer connection.
                    sender.replaceTrack(cameraTrack);
                }
            });
        });

        // Restore the local preview and the appropriate camera control state.
        if (cameraTrack) {
            localVideo.srcObject = callStream;
            localVideo.classList.remove("sharing-screen");
            cameraCallButton.disabled = false;
        } else {
            localVideo.srcObject = null;
            localVideo.classList.remove("sharing-screen");
            cameraCallButton.disabled = true;
        }
        shareScreenButton.textContent = "Share screen";
        showCallStatus("Screen sharing stopped.");
    }

    // Ask the browser to capture a screen or window only after a call is joined.
    shareScreenButton.addEventListener("click", function () {
        if (screenStream) {
            stopScreenShare();
            return;
        }
        // getDisplayMedia is unavailable in some browsers or non-secure contexts.
        if (!callParticipantId || !navigator.mediaDevices
                || typeof navigator.mediaDevices.getDisplayMedia !== "function") {
            showCallStatus("Screen sharing is not available in this browser.");
            return;
        }

        // The browser permission prompt is opened only by this explicit button click.
        navigator.mediaDevices.getDisplayMedia({ video: true })
            .then(function (stream) {
                var track = stream.getVideoTracks()[0];
                if (!track) {
                    // Refuse an incomplete capture and stop any returned tracks.
                    stream.getTracks().forEach(function (item) {
                        item.stop();
                    });
                    throw new Error("No screen track was returned.");
                }
                // Save the screen stream separately from the camera and microphone stream.
                screenStream = stream;
                track.contentHint = "detail";
                // Use contain cropping for the local preview so the full screen remains visible.
                localVideo.classList.add("sharing-screen");

                // Swap screen video into every existing peer connection.
                Object.keys(callPeers).forEach(function (participantId) {
                    var peer = callPeers[participantId];
                    var sender = peer.connection.getSenders().find(function (item) {
                        return item.track && item.track.kind === "video";
                    });
                    if (sender) {
                        // A successful replaceTrack keeps the existing WebRTC connection intact.
                        sender.replaceTrack(track).catch(function (error) {
                            showCallStatus("Could not share the screen: " + error.message);
                        });
                    } else {
                        // Add a video track if this peer has no camera or screen track yet.
                        peer.connection.addTrack(track, stream);
                    }
                });

                // Show the chosen screen in the sharer's local preview.
                localVideo.srcObject = stream;
                shareScreenButton.textContent = "Stop sharing";
                cameraCallButton.disabled = true;
                showCallStatus("Your screen is being shared in the call.");

                // Handle the browser's built-in Stop sharing control as a normal stop.
                track.addEventListener("ended", function () {
                    stopScreenShare();
                });
            })
            .catch(function (error) {
                // Report denial separately from other browser or network errors.
                if (error.name !== "NotAllowedError") {
                    showCallStatus("Could not start screen sharing: " + error.message);
                } else {
                    showCallStatus("Screen sharing was canceled.");
                }
            });
    });

    /* Add one chat message to the visible conversation. */
    function appendMessage(message) {
        var currentProfile = window.SiteProfile.current();
        var bubble = document.createElement("div");
        bubble.className = "msg";
        if (currentProfile && message.user_id === currentProfile.user_id) {
            bubble.classList.add("mine");
        } else {
            bubble.classList.add("theirs");
        }

        var author = document.createElement("strong");
        author.textContent = window.SiteProfile.memberLabel(
            message.real_name,
            message.account_number,
            message.verified
        );
        bubble.appendChild(author);

        var body = document.createElement("div");
        body.textContent = message.text;
        bubble.appendChild(body);
        messages.appendChild(bubble);
        messages.scrollTop = messages.scrollHeight;
    }

    /* List this profile's conversations, newest activity first. */
    function loadChatList(profile) {
        if (!profile) {
            chatList.innerHTML = "";
            chatListStatus.textContent = "Create a profile to see chat rooms for your questions.";
            return;
        }

        fetch("/api/chats/me")
            .then(function (response) {
                return response.json().then(function (data) {
                    if (!response.ok) {
                        throw new Error(data.detail || "Your chat rooms could not be loaded.");
                    }
                    return data;
                });
            })
            .then(function (rooms) {
                chatList.innerHTML = "";
                if (!rooms.length) {
                    chatListStatus.textContent =
                        "No chat rooms yet. When someone replies to one of your questions, the conversation will appear here.";
                    return;
                }

                chatListStatus.textContent = rooms.length === 1
                    ? "1 chat room"
                    : rooms.length + " chat rooms";
                rooms.forEach(function (chat) {
                    var card = document.createElement("article");
                    card.className = "card";

                    var heading = document.createElement("strong");
                    heading.textContent = chat.my_question;
                    card.appendChild(heading);

                    var otherQuestion = document.createElement("span");
                    otherQuestion.textContent = "Also about: " + chat.questions.join(" | ");
                    card.appendChild(otherQuestion);

                    var latest = document.createElement("span");
                    latest.textContent = (chat.last_message_from_me
                        ? "Your last message: "
                        : "Reply from " + chat.last_sender + ": ")
                        + chat.last_message;
                    card.appendChild(latest);

                    var openLink = document.createElement("a");
                    openLink.href = "chat.html?room=" + encodeURIComponent(chat.room);
                    openLink.textContent = chat.last_message_from_me
                        ? "Open chat history"
                        : "Open chat to reply";
                    card.appendChild(openLink);

                    chatList.appendChild(card);
                });
            })
            .catch(function (error) {
                chatListStatus.textContent = error.message;
            });
    }

    // Shows no questions until a major is chosen, then groups matches under selected minor badges.
    function renderQuestionDirectory() {
        var major = questionBadgePicker.getMajor();
        var selectedMinors = questionBadgePicker.getMinorTags();
        var query = questionSearch.value.trim().toLocaleUpperCase();
        var groups = Object.create(null);
        var visibleQuestions = Object.create(null);

        questionDirectory.innerHTML = "";
        if (!major) {
            questionDirectoryStatus.textContent = "Choose a major badge to find questions.";
            return;
        }

        publicQuestions.forEach(function (question) {
            var tags = Array.isArray(question.tags) ? question.tags : [];
            var searchable = question.question.toLocaleUpperCase() + " "
                + (question.description || "").toLocaleUpperCase() + " " + tags.join(" ");
            if (tags.indexOf(major) === -1) {
                return;
            }
            if (selectedMinors.length
                    && !selectedMinors.some(function (badge) { return tags.indexOf(badge) !== -1; })) {
                return;
            }
            if (query && searchable.indexOf(query) === -1) {
                return;
            }

            var resultBadges = selectedMinors.length ? selectedMinors : [major];
            resultBadges.filter(function (badge) {
                return tags.indexOf(badge) !== -1;
            }).forEach(function (tag) {
                groups[tag] = groups[tag] || [];
                groups[tag].push({ question: question, tags: tags });
                visibleQuestions[question.id] = true;
            });
        });

        var badgeNames = Object.keys(groups).sort();
        if (!badgeNames.length) {
            questionDirectoryStatus.textContent = publicQuestions.length
                ? "No questions match that search."
                : "No public questions yet.";
            return;
        }

        var questionCount = Object.keys(visibleQuestions).length;
        questionDirectoryStatus.textContent = questionCount === 1
            ? "1 matching public question."
            : questionCount + " matching public questions.";
        badgeNames.forEach(function (badge) {
            var heading = document.createElement("h3");
            heading.textContent = badge;
            questionDirectory.appendChild(heading);

            groups[badge].forEach(function (result) {
                var question = result.question;
                var card = document.createElement("article");
                card.className = "card";

                var details = document.createElement("details");
                var summary = document.createElement("summary");
                summary.textContent = question.question;
                details.appendChild(summary);

                var description = document.createElement("p");
                description.textContent = question.description || "No description was provided.";
                details.appendChild(description);

                var questionBadges = document.createElement("span");
                questionBadges.textContent = "Badges: " + (result.tags.length
                    ? result.tags.join(", ")
                    : "None");
                details.appendChild(questionBadges);

                var joinLink = document.createElement("a");
                joinLink.href = "chat.html?room=" + encodeURIComponent(question.room);
                joinLink.textContent = "Join question chat";
                details.appendChild(joinLink);
                card.appendChild(details);
                questionDirectory.appendChild(card);
            });
        });
    }

    // Loads the public questions and their saved badges from the server's existing room directory.
    function loadQuestionDirectory() {
        fetch("/api/public-rooms")
            .then(function (response) {
                return response.json().then(function (data) {
                    if (!response.ok) {
                        throw new Error(data.detail || "Public questions could not be loaded.");
                    }
                    return data;
                });
            })
            .then(function (questions) {
                publicQuestions = questions;
                renderQuestionDirectory();
            })
            .catch(function (error) {
                questionDirectoryStatus.textContent = error.message;
            });
    }

    // Re-render the public directory immediately when text or badge selections change.
    questionSearch.addEventListener("input", renderQuestionDirectory);
    questionBadgePicker.onChange(renderQuestionDirectory);
    renderQuestionDirectory();
    loadQuestionDirectory();

    /* Load the two questions that identify this chat room. */
    function loadTopic() {
        if (!hasValidRoom) {
            topic.textContent = "Select one of your chat rooms above, or open a matching question's Answer in chat link.";
            sendButton.disabled = true;
            callSection.hidden = !hasValidRoom;
            showMessage("No question chat selected.");
            return Promise.resolve(false);
        }

        return fetch("/api/room/" + encodeURIComponent(room))
            .then(function (response) {
                return response.json().then(function (data) {
                    if (!response.ok) {
                        throw new Error(data.detail || "This chat could not be loaded.");
                    }
                    callSection.hidden = false;
                    topic.textContent = "About: " + data.questions.join(" | ") // Shows all question topics attached to this room.
                        + (data.public ? " — Public room; share this page link so others can join." : "");
                    return true;
                });
            })
            .catch(function (error) {
                showMessage(error.message);
                return false;
            });
    }

    /* Open the live connection and sign in if this browser has a profile. */
    function connect() {
        if (!hasValidRoom) {
            return;
        }
        if (socket) {
            resetCall(false);
            socket.close();
        }

        var protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        var connection = new WebSocket(protocol + "//" + window.location.host
            + "/ws/" + encodeURIComponent(room));
        socket = connection;
        sendButton.disabled = true;
        joinCallButton.disabled = true;
        joinAudioButton.disabled = true;

        connection.onopen = function () {
            if (!window.SiteProfile.current()) {
                showMessage("Viewing chat history. Create a profile to reply.");
            }
        };
        connection.onmessage = function (event) {
            var data = JSON.parse(event.data);
            if (data.type === "auth") {
                sendButton.disabled = false;
                joinCallButton.disabled = false;
                joinAudioButton.disabled = false;
                showMessage("Connected. Your replies show your name as unverified.");
                showCallStatus("Connected. Join an audio/video call when you're ready.");
            } else if (data.type === "call-joined") {
                callParticipantId = data.participant_id;
                joinCallButton.hidden = true;
                joinAudioButton.hidden = true;
                leaveCallButton.hidden = false;
                muteCallButton.disabled = false;
                cameraCallButton.disabled = callStream.getVideoTracks().length === 0;
                // Enable sharing only after this participant has joined the call.
                shareScreenButton.disabled = false;
                data.peers.forEach(function (peer) {
                    createCallPeer(peer.id, peer.real_name, callParticipantId < peer.id);
                });
                updateCallStatus();
            } else if (data.type === "call-peer-joined") {
                if (callParticipantId) {
                    var participant = data.participant;
                    createCallPeer(
                        participant.id,
                        participant.real_name,
                        callParticipantId < participant.id
                    );
                    updateCallStatus();
                }
            } else if (data.type === "call-signal") {
                handleCallSignal(data);
            } else if (data.type === "call-peer-left") {
                removeCallPeer(data.participant_id);
            } else if (data.type === "call-error") {
                showCallStatus(data.message);
            } else if (data.type === "error") {
                if (callStream && !callParticipantId) {
                    resetCall(false);
                }
                showMessage(data.message);
                showCallStatus(data.message);
            } else if (data.type !== "signal") {
                appendMessage(data);
                loadChatList(window.SiteProfile.current());
            }
        };
        connection.onerror = function () {
            sendButton.disabled = true;
            joinCallButton.disabled = true;
            joinAudioButton.disabled = true;
            showMessage("The chat connection failed. Refresh the page to try again.");
        };
        connection.onclose = function () {
            if (socket === connection) {
                resetCall(false);
                sendButton.disabled = true;
                joinCallButton.disabled = true;
                joinAudioButton.disabled = true;
                if (chatStatus.textContent.indexOf("failed") === -1) {
                    showMessage("The chat connection closed.");
                }
                showCallStatus("The chat connection closed; the call has ended.");
            }
        };
    }

    /* Send a reply only after the server confirms profile sign-in. */
    sendForm.addEventListener("submit", function (event) {
        event.preventDefault();
        var profile = window.SiteProfile.current();
        if (!profile) {
            document.getElementById("profileStatus").textContent =
                "Create a profile before replying. Your name will be public and unverified.";
            return;
        }
        if (!socket || socket.readyState !== WebSocket.OPEN) {
            showMessage("Wait for the chat to connect before replying.");
            return;
        }

        var text = textInput.value.trim();
        if (!text) {
            return;
        }
        socket.send(JSON.stringify({ text: text }));
        textInput.value = "";
    });

    // Load the personal room list even when no particular room is open.
    sendButton.disabled = true;
    window.SiteProfile.ready.then(loadChatList);
    window.addEventListener("profilechange", function (event) {
        loadChatList(event.detail);
    });
    loadTopic().then(function (validRoom) {
        if (!validRoom) {
            return;
        }
        return window.SiteProfile.ready.then(connect);
    });
    window.addEventListener("profilechange", connect);
})();
