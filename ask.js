/* QUESTION FORM
   Sends a question with its badges and shows similar questions from the server.
*/

var askForm = document.getElementById("askForm");
var resultBox = document.getElementById("result");
var questionInput = document.getElementById("question");
var descriptionInput = document.getElementById("description");
var majorInput = document.getElementById("major");
var questionSubmitButton = askForm.querySelector("button[type='submit']");

// Wait for profile lookup so a question cannot be posted before the profile is ready.
questionSubmitButton.disabled = true;
window.SiteProfile.ready.then(function () {
    questionSubmitButton.disabled = false;
});

/* Put status and error messages in the result area. */
function showMessage(message) {
    resultBox.textContent = message;
}

/* Build a result card for every similar question returned by the server. */
function showMatches(matches, questionId) {
    resultBox.innerHTML = "";
    var heading = document.createElement("h2");
    heading.textContent = matches.length
        ? "Similar questions with matching badges"
        : "Your question was saved. No similar questions with matching badges were found.";
    resultBox.appendChild(heading);

    matches.forEach(function (match) {
        var card = document.createElement("article");
        card.className = "card";

        var title = document.createElement("strong");
        title.textContent = match.question;
        card.appendChild(title);

        var author = document.createElement("span");
        author.textContent = "Asked by " + match.real_name
            + (match.verified ? " — Verified" : " — Unverified");
        card.appendChild(author);

        if (match.description) {
            var description = document.createElement("span");
            description.textContent = match.description;
            card.appendChild(description);
        }

        var tags = document.createElement("span");
        tags.textContent = "Shared badges: " + match.shared_tags.join(", ");
        card.appendChild(tags);

        var similarity = document.createElement("span");
        similarity.className = "small";
        similarity.textContent = Math.round(match.score * 100) + "% question-word similarity";
        card.appendChild(similarity);

        var answerLink = document.createElement("a");
        answerLink.href = "chat.html?room=" + [questionId, match.id].sort(function (a, b) {
            return a - b;
        }).join("-");
        answerLink.textContent = "Answer in chat";
        card.appendChild(answerLink);

        resultBox.appendChild(card);
    });
}

askForm.addEventListener("submit", function (event) {
    event.preventDefault();

    var profile = window.SiteProfile.current();
    if (!profile) {
        document.getElementById("profileStatus").textContent =
            "Create a profile before posting. Your name will be public and unverified.";
        return;
    }

    // The major badge and selected minor badges are both used for matching.
    var tags = [];
    if (majorInput.value) {
        tags.push(majorInput.value);
    }
    if (Array.isArray(window.picked)) {
        tags = tags.concat(window.picked);
    }

    questionSubmitButton.disabled = true;
    showMessage("Submitting your question...");

    // The browser's HttpOnly session cookie identifies the profile to the server.
    fetch("/api/questions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
            question: questionInput.value,
            description: descriptionInput.value,
            tags: tags
        })
    })
        .then(function (response) {
            return response.json().then(function (data) {
                if (!response.ok) {
                    throw new Error(data.detail || "Your question could not be submitted.");
                }
                return data;
            });
        })
        .then(function (data) {
            showMatches(data.matches, data.id);
            askForm.reset();
            majorInput.dispatchEvent(new Event("change"));
        })
        .catch(function (error) {
            showMessage(error.message);
        })
        .finally(function () {
            questionSubmitButton.disabled = false;
        });
});
