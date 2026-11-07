/* ACCOUNT SIGN-IN
   The server keeps the account and signs this browser in with an HttpOnly cookie.
   The browser keeps only the display name in memory, not the password or session token.
*/
(function () {
    var profile = null;
    var oldProfileId = localStorage.getItem("user_id");
    var status = document.getElementById("profileStatus");
    var registerForm = document.getElementById("registerForm");
    var loginForm = document.getElementById("loginForm");
    var logoutButton = document.getElementById("logoutButton");

    function showSignedOut() {
        profile = null;
        status.textContent = "Create an account or sign in before posting or replying.";
        registerForm.hidden = false;
        loginForm.hidden = true;
        logoutButton.hidden = true;
    }

    function showSignedIn() {
        status.textContent = "Signed in as " + profile.real_name
            + (profile.verified ? " — Verified" : " — Unverified");
        registerForm.hidden = true;
        loginForm.hidden = true;
        logoutButton.hidden = false;
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
                    verified: data.verified
                };
                oldProfileId = null;
                localStorage.removeItem("user_id");
                form.reset();
                showSignedIn();
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

    /* Other page scripts wait for account status and read the current public profile. */
    window.SiteProfile = {
        ready: ready,
        current: function () { return profile; }
    };
})();
