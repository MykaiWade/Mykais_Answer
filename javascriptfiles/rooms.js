/* PUBLIC QUESTION ROOMS
   Lists joinable question chats and their live activity and message totals.
*/
(function () {
    var createForm = document.getElementById("createRoomForm"); // Finds the form used to create public question rooms.
    var questionInput = document.getElementById("roomQuestion"); // Finds the field containing the new room topic.
    var status = document.getElementById("roomStatus"); // Finds the live status and error message area.
    var activeRooms = document.getElementById("activeRooms"); // Finds the list of rooms with connected visitors.
    var busyRooms = document.getElementById("busyRooms"); // Finds the list of rooms ranked by saved messages.
    var roomList = document.getElementById("publicRoomList"); // Finds the complete public room directory.
    var submitButton = createForm.querySelector("button[type='submit']"); // Gets the room creation control.
    submitButton.disabled = true; // Prevents submission until the account status is known.

    // Builds a room card with its topic, activity, join link, and shareable invitation.
    function makeRoomCard(room) {
        var card = document.createElement("article"); // Creates a semantic card for one public room.
        card.className = "card"; // Applies the site's existing card styling.

        var heading = document.createElement("strong"); // Creates the visible room-topic heading.
        heading.textContent = room.question; // Uses text content to display the topic safely.
        card.appendChild(heading); // Adds the topic heading to the room card.

        var details = document.createElement("span"); // Creates a summary of room activity.
        details.textContent = room.active_people + " active " // Shows how many unique visitors are connected.
            + (room.active_people === 1 ? "person" : "people")
            + " · " + room.message_count + " "
            + (room.message_count === 1 ? "message" : "messages");
        card.appendChild(details); // Adds the activity summary under the room topic.

        var joinLink = document.createElement("a"); // Creates the link that opens the selected room.
        joinLink.href = "chat.html?room=" + encodeURIComponent(room.room); // Encodes the room key in the chat URL.
        joinLink.textContent = "Join room"; // Labels the room-opening link.
        card.appendChild(joinLink); // Adds the join link to the card.

        var invite = window.location.origin + "/chat.html?room=" // Builds a complete invitation link for this site.
            + encodeURIComponent(room.room);
        var shareButton = document.createElement("button"); // Creates the control for copying the invitation.
        shareButton.type = "button"; // Keeps the share action from submitting the room form.
        shareButton.textContent = "Copy invite link"; // Describes the action to visitors.
        shareButton.addEventListener("click", function () { // Copies the invitation or shows its URL as a fallback.
            if (!navigator.clipboard || !navigator.clipboard.writeText) {
                status.textContent = "Copy this room link to invite others: " + invite; // Shows the link if clipboard access is unavailable.
                return; // Stops after displaying the manual-copy fallback.
            }
            navigator.clipboard.writeText(invite) // Requests that the browser copy the invitation URL.
                .then(function () {
                    status.textContent = "Invite link copied. Share it so others can join."; // Confirms the link was copied.
                })
                .catch(function (error) {
                    status.textContent = "Could not copy the invite link: " + error.message // Reports clipboard errors.
                        + " Copy this link instead: " + invite;
                });
        });
        card.appendChild(shareButton); // Places the invitation control beside the join link.
        return card; // Returns the fully built room card.
    }

    // Replaces a room list with cards or a message when there are no matching rooms.
    function renderRooms(target, rooms, emptyMessage) {
        target.innerHTML = ""; // Clears any cards from the previous activity refresh.
        if (!rooms.length) {
            target.textContent = emptyMessage; // Explains why this list has no rooms to display.
            return; // Avoids trying to render an empty list.
        }
        rooms.forEach(function (room) { // Renders each room in its current ranking order.
            target.appendChild(makeRoomCard(room)); // Adds the room's card to this list.
        });
    }

    // Loads room totals and renders the active, most-messaged, and all-room lists.
    function loadRooms() {
        fetch("/api/public-rooms") // Requests the latest room list and live activity counts.
            .then(function (response) { // Checks the HTTP result before using the response data.
                return response.json().then(function (data) { // Parses the server's JSON body.
                    if (!response.ok) {
                        throw new Error(data.detail || "Public rooms could not be loaded."); // Displays the server's error.
                    }
                    return data; // Passes the public rooms to the rendering step.
                });
            })
            .then(function (rooms) { // Sorts and displays successful room results.
                var byActive = rooms.slice().sort(function (a, b) { // Ranks by active people, messages, then recency.
                    return b.active_people - a.active_people
                        || b.message_count - a.message_count
                        || b.created - a.created;
                });
                var byMessages = rooms.slice().sort(function (a, b) { // Ranks by messages, active people, then recency.
                    return b.message_count - a.message_count
                        || b.active_people - a.active_people
                        || b.created - a.created;
                });
                renderRooms(activeRooms, // Shows only rooms that currently have visitors.
                    byActive.filter(function (room) { // Excludes inactive rooms from the live list.
                        return room.active_people > 0; // Keeps rooms with at least one connected visitor.
                    }).slice(0, 5),
                    rooms.length
                        ? "No one is active in a room right now."
                        : "No public rooms yet. Create the first one below.");
                renderRooms(busyRooms, byMessages.slice(0, 5), // Shows the five rooms with the most saved messages.
                    "No public rooms yet. Create the first one below.");
                renderRooms(roomList, byActive, // Shows every public room in activity order.
                    "No public rooms yet. Create the first one below.");
                if (status.textContent === "Loading public rooms...") { // Replaces the initial loading message once.
                    status.textContent = rooms.length
                        ? "Activity refreshes every 10 seconds. Share any room invite link to let others join."
                        : "No public rooms yet. Sign in to create one.";
                }
            })
            .catch(function (error) { // Shows network or server errors rather than hiding them.
                status.textContent = error.message; // Makes the room-list failure visible on the page.
            });
    }

    createForm.addEventListener("submit", function (event) { // Creates a public room when its form is submitted.
        event.preventDefault(); // Keeps the browser from navigating away during submission.
        if (!window.SiteProfile.current()) {
            status.textContent = "Create an account or sign in before creating a public room."; // Explains the account requirement.
            return; // Prevents an unauthenticated room-creation request.
        }

        submitButton.disabled = true; // Prevents duplicate submissions while the room is being saved.
        status.textContent = "Creating your public room..."; // Informs the user that creation is in progress.
        fetch("/api/public-rooms", { // Sends the new topic to the authenticated room-creation endpoint.
            method: "POST", // Creates rather than reads a room.
            headers: { "Content-Type": "application/json" }, // Identifies the request body as JSON.
            body: JSON.stringify({ question: questionInput.value }) // Sends the typed topic to the server.
        })
            .then(function (response) { // Parses the result and handles server errors.
                return response.json().then(function (data) { // Reads the returned room details or error message.
                    if (!response.ok) {
                        throw new Error(data.detail || "The public room could not be created."); // Surfaces creation failures.
                    }
                    return data; // Passes the new room details to the redirect step.
                });
            })
            .then(function (room) { // Opens the room after successful creation.
                createForm.reset(); // Clears the question field before leaving the page.
                status.textContent = "Room created. Share its invite link so others can join."; // Confirms successful creation.
                window.location.href = "chat.html?room=" // Navigates to the new public discussion.
                    + encodeURIComponent(room.room);
            })
            .catch(function (error) { // Displays authentication or server errors from the request.
                status.textContent = error.message; // Keeps the failure visible so the user can respond.
            })
            .finally(function () { // Restores the submit button after the request settles.
                submitButton.disabled = false; // Allows another room attempt after an error.
            });
    });

    window.SiteProfile.ready.then(function (profile) { // Enables room creation only after account lookup completes.
        submitButton.disabled = !profile; // Requires an authenticated profile to create a room.
        if (!profile) {
            status.textContent = "Sign in to create a room. Anyone can join existing rooms."; // Explains access for signed-out visitors.
        }
    });
    window.addEventListener("profilechange", function (event) { // Updates room-creation access after sign-in changes.
        submitButton.disabled = !event.detail; // Enables or disables the form based on the new profile.
        if (!event.detail) {
            status.textContent = "Sign in to create a room. Anyone can join existing rooms."; // Reminds signed-out visitors they can still join.
        }
    });

    loadRooms(); // Shows public rooms immediately when the page opens.
    window.setInterval(loadRooms, 10000); // Refreshes room counts and rankings every ten seconds.
})();
