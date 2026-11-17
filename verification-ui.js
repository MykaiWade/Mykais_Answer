/*
 * - Handles the one-time QR link emailed during account registration.
 * - Loaded by verify.html; asks server.py to check the token and approve the member.
 */
(function () {
    var token = window.location.hash.slice(1);
    var status = document.getElementById("verificationStatus");
    var signInSection = document.getElementById("verifierSignIn");
    var loginForm = document.getElementById("verificationLoginForm");
    var approvalSection = document.getElementById("verificationApproval");
    var memberLabel = document.getElementById("verificationMember");
    var approveButton = document.getElementById("approveVerificationButton");
    var accountNumber = null;

    if (token) {
        window.history.replaceState(null, "", window.location.pathname + window.location.search);
    }

    function postJson(url, data) {
        return fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data)
        }).then(function (response) {
            return response.json().then(function (body) {
                if (!response.ok) {
                    if (response.status === 401) {
                        signInSection.hidden = false;
                        approvalSection.hidden = true;
                        status.textContent = "Sign in with the verified Mykai Wade account to review this QR.";
                    }
                    throw new Error(body.detail || "The verification request failed.");
                }
                return body;
            });
        });
    }

    // Load the member linked to the one-time token before showing the approval form.
    function loadRequest() {
        if (!token) {
            status.textContent = "This page needs the QR link from the verification email.";
            return;
        }
        status.textContent = "Checking the QR code...";
        postJson("/api/verification/request", { token: token })
            .then(function (member) {
                accountNumber = member.account_number;
                memberLabel.textContent = member.real_name + " " + accountNumber;
                signInSection.hidden = true;
                approvalSection.hidden = false;
                status.textContent = "Review this member before approving.";
            })
            .catch(function (error) {
                status.textContent = error.message;
            });
    }

    // Require a signed-in verifier before the server will accept approval.
    loginForm.addEventListener("submit", function (event) {
        event.preventDefault();
        var button = loginForm.querySelector("button[type='submit']");
        button.disabled = true;
        postJson("/api/auth/login", {
            email: document.getElementById("verificationEmail").value.trim(),
            password: document.getElementById("verificationPassword").value
        })
            .then(function () {
                loginForm.reset();
                loadRequest();
            })
            .catch(function (error) {
                status.textContent = error.message;
            })
            .finally(function () {
                button.disabled = false;
            });
    });

    approveButton.addEventListener("click", function () {
        approveButton.disabled = true;
        status.textContent = "Approving verification...";
        postJson("/api/verification/approve", { token: token })
            .then(function (member) {
                approvalSection.hidden = true;
                status.textContent = member.real_name + " " + member.account_number
                    + " # is now verified.";
            })
            .catch(function (error) {
                status.textContent = error.message;
                approveButton.disabled = false;
            });
    });

    loadRequest();
})();
