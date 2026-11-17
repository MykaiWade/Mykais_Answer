const title = document.getElementById("welcomeTitle");

let leftClicks = 0;
let secret1 = false;

title.addEventListener("click",function() {
    leftClicks++

    if (leftClicks === 10) {
        secret1 = !secret1
        title.classList.remove("secret-active");
        void title.offsetWidth;
        title.classList.add("secret-active");

        if (secret1) {
            title.textContent = "emocleW";
        } else {
            title.textContent = "Welcome";
        }

        leftClicks = 0;
    }
});