
const loadingScreen = document.getElementById("profileLoading");
const loadingMessage = document.getElementById("loadingMessage");
const profileContent = document.getElementById("profileContent");

// Temporary profile data for beta testing
const testProfile = {
    username: "Artey",
    userID: "user-1001",
    displayName: "Artey",
    bio: "Creating my own little corner of the internet."
};

async function loadProfile() {
    try {
        loadingMessage.textContent =
            "Retrieving your profile information...";

        // Simulate waiting for a server response.
        // Replace this with a real fetch request later.
        await new Promise(resolve => setTimeout(resolve, 2000));

        // Populate the profile
        document.getElementById("username").textContent =
            testProfile.username;

        document.getElementById("userID").textContent =
            testProfile.userID;

        document.getElementById("displayName").textContent =
            testProfile.displayName;

        document.getElementById("bio").textContent =
            testProfile.bio;

        // Reveal the profile after loading
        loadingScreen.hidden = true;
        profileContent.hidden = false;

    } catch (error) {
        loadingMessage.textContent =
            "Something went wrong while loading your profile. Please try again.";
    }
}

loadProfile();
