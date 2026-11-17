/*
 * - Shows the signed-in profile's public details and saved questions.
 * - Connects profile.html to profile.js and server.py's private question API.
*/
(function () {
    var profileStatus = document.getElementById("profileStatus");
    var profileDetails = document.getElementById("profileDetails");
    var profileName = document.getElementById("profileName");
    var profileVerification = document.getElementById("profileVerification");
    var questionsStatus = document.getElementById("questionsStatus");
    var questionsList = document.getElementById("myQuestions");

    function renderQuestions(questions) {
        questionsList.innerHTML = "";
        if (!questions.length) {
            questionsStatus.textContent = "You have not asked any questions yet.";
            return;
        }

        questionsStatus.textContent = questions.length + " "
            + (questions.length === 1 ? "question" : "questions");
        questions.forEach(function (question) {
            var card = document.createElement("article");
            card.className = "card";

            var title = document.createElement("strong");
            title.textContent = question.question;
            card.appendChild(title);

            var date = document.createElement("span");
            date.className = "small";
            if (Number.isFinite(question.created)) {
                var time = document.createElement("time");
                time.dateTime = new Date(question.created * 1000).toISOString();
                time.textContent = new Date(question.created * 1000).toLocaleString();
                date.appendChild(time);
            } else {
                date.textContent = "Date unavailable";
            }
            card.appendChild(date);

            if (question.description) {
                var description = document.createElement("p");
                description.textContent = question.description;
                card.appendChild(description);
            }

            var tags = document.createElement("span");
            tags.textContent = "Badges: " + (question.tags.length ? question.tags.join(", ") : "None");
            card.appendChild(tags);
            questionsList.appendChild(card);
        });
    }

    function loadQuestions() {
        var profile = window.SiteProfile.current();
        profileDetails.hidden = !profile;
        questionsList.innerHTML = "";
        if (!profile) {
            questionsStatus.textContent = "Sign in to see your questions.";
            return;
        }

        profileName.textContent = profile.real_name;
        profileVerification.textContent = profile.verified ? "Verified" : "Unverified";
        questionsStatus.textContent = "Loading your questions...";

        fetch("/api/questions/me")
            .then(function (response) {
                return response.json().then(function (data) {
                    if (!response.ok) {
                        throw new Error(data.detail || "Your questions could not be loaded.");
                    }
                    return data;
                });
            })
            .then(function (data) {
                renderQuestions(data.questions);
            })
            .catch(function (error) {
                questionsStatus.textContent = error.message;
            });
    }

    window.SiteProfile.ready.then(loadQuestions);
    window.addEventListener("profilechange", loadQuestions);
})();
