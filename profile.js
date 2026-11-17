/*
 * - Handles account registration, sign-in, sign-out, and current-profile state.
 * - Connects account forms to server.py's auth API and tells profile-page.js when sign-in changes.
*/
(function () {
    var profile = null;
    var oldProfileId = localStorage.getItem("user_id");
    var status = document.getElementById("profileStatus");
    var registerForm = document.getElementById("registerForm");
    var loginForm = document.getElementById("loginForm");
    var logoutButton = document.getElementById("logoutButton");
    var resendVerificationButton = document.getElementById("resendVerificationButton");
    var verificationQrImage = document.getElementById("verificationQrImage");
    var isProfilePage = Boolean(document.getElementById("showProfileQrButton"));

    function memberLabel(realName, accountNumber, verified) {
        var label = realName || "Unknown member";
        if (accountNumber !== null && accountNumber !== undefined) {
            label += " " + accountNumber;
        }
        return label + (verified ? " # — Verified" : " — Unverified");
    }

    function showSignedOut() {
        profile = null;
        status.textContent = isProfilePage
            ? "Sign in or create an account to share or scan contact QR codes."
            : "Create an account or sign in before posting or replying.";
        registerForm.hidden = false;
        loginForm.hidden = true;
        logoutButton.hidden = true;
        if (resendVerificationButton) {
            resendVerificationButton.hidden = true;
        }
        if (verificationQrImage) {
            verificationQrImage.hidden = true;
        }
    }

    function showSignedIn() {
        status.textContent = "Signed in as " + memberLabel(
            profile.real_name,
            profile.account_number,
            profile.verified
        );
        registerForm.hidden = true;
        loginForm.hidden = true;
        logoutButton.hidden = false;
        if (resendVerificationButton) {
            resendVerificationButton.hidden = profile.verified;
        }
        if (verificationQrImage && profile.verified) {
            verificationQrImage.hidden = true;
        }
    }

    function sendForm(form, url, details) {
        var button = form.querySelector("button[type='submit']");
        button.disabled = true;
        status.textContent = "Please wait...";

        return fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(details)
        })
            .then(function (response) {
                return response.json().then(function (data) {
                    if (!response.ok) {
                        throw new Error(data.detail || "The account request failed.");
                    }
                    return data;
                });
            })
            .then(function (data) {
                profile = {
                    user_id: data.user_id,
                    real_name: data.real_name,
                    account_number: data.account_number,
                    public_id: data.public_id,
                    verified: data.verified
                };
                oldProfileId = null;
                localStorage.removeItem("user_id");
                form.reset();
                showSignedIn();
                if (data.verification_email_sent) {
                    status.textContent += " A verification QR code was sent to your email.";
                }
                window.dispatchEvent(new CustomEvent("profilechange", { detail: profile }));
            })
            .catch(function (error) {
                status.textContent = error.message;
            })
            .finally(function () {
                button.disabled = false;
            });
    }

    /* Check whether this browser already has a valid sign-in cookie. */
    var ready = fetch("/api/auth/me")
        .then(function (response) {
            if (response.status === 401) {
                showSignedOut();
                return null;
            }
            if (!response.ok) {
                throw new Error("Your sign-in could not be checked.");
            }
            return response.json().then(function (data) {
                profile = data;
                showSignedIn();
                return profile;
            });
        })
        .catch(function (error) {
            status.textContent = error.message;
            return null;
        });

    /* Register a new account, or upgrade the old profile in this browser. */
    registerForm.addEventListener("submit", function (event) {
        event.preventDefault();
        sendForm(registerForm, "/api/auth/register", {
            real_name: document.getElementById("realName").value.trim(),
            email: document.getElementById("registerEmail").value.trim(),
            password: document.getElementById("registerPassword").value,
            legacy_user_id: oldProfileId
        });
    });

    /* Sign back into an existing account. */
    loginForm.addEventListener("submit", function (event) {
        event.preventDefault();
        sendForm(loginForm, "/api/auth/login", {
            email: document.getElementById("loginEmail").value.trim(),
            password: document.getElementById("loginPassword").value
        });
    });

    document.getElementById("showLogin").addEventListener("click", function () {
        registerForm.hidden = true;
        loginForm.hidden = false;
        status.textContent = "Sign in with your email and password.";
    });

    document.getElementById("showRegister").addEventListener("click", function () {
        loginForm.hidden = true;
        registerForm.hidden = false;
        status.textContent = "Create an account. Your old questions in this browser will be kept.";
    });

    logoutButton.addEventListener("click", function () {
        fetch("/api/auth/logout", { method: "POST" })
            .then(function (response) {
                if (!response.ok) {
                    throw new Error("You could not be signed out.");
                }
                showSignedOut();
                window.dispatchEvent(new CustomEvent("profilechange", { detail: null }));
            })
            .catch(function (error) {
                status.textContent = error.message;
            });
    });

    if (resendVerificationButton) {
        resendVerificationButton.addEventListener("click", function () {
                resendVerificationButton.disabled = true;
                status.textContent = "Sending a new verification QR code...";
                fetch("/api/verification/resend", { method: "POST" })
                    .then(function (response) {
                        return response.json().then(function (data) {
                            if (!response.ok) {
                                throw new Error(data.detail || "A new QR code could not be sent.");
                            }
                            return data;
                        });
                    })
                    .then(function (data) {
                        status.textContent = data.message;
                        if (verificationQrImage && data.qr_code) {
                            verificationQrImage.src = "data:image/png;base64," + data.qr_code;
                            verificationQrImage.hidden = false;
                        }
                    })
                    .catch(function (error) {
                        status.textContent = error.message;
                    })
                    .finally(function () {
                        resendVerificationButton.disabled = false;
                });
            });
    }

    /* Other page scripts wait for account status and read the current public profile. */
    window.SiteProfile = {
        ready: ready,
        current: function () { return profile; },
        memberLabel: memberLabel
    };
})();
