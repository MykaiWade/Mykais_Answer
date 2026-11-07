# Mykais_Answer
Website for Mykai's Answer
CREATOR: MYKAI WADE


THINGS WE SUPPORT:

PEOPLE COME TO THIS APP/WEBSITE TO LEARN, SO MAKE A GOOD LEARNING ENVIROMENT

WE SUPPORT AND JUDGE PEOPLE FOR WHO THEY ARE AND NOT WHAT THEY ARE

THERE IS NOT SUCH THING AS A BAD IDEA JUST AN UNFINISHED ONE

YOU ARE YOUR OWN PERSON AND CAN MAKE YOUR OWN CHOICES IF SOMETHING DOES NOT FEEL RIGHT SPEAK UP

WE SUPPORT CHANGING FOR THE BETTER AND PEOPLE WILL HAVE THE CHANCE TO JOIN IF THEY WANT TO CHANGE

WE DO NOT HAVE ALL THE ANSWERS AND DO NOT KNOW EVERYTHING (WE WILL HELP THE BEST WE CAN)

APP USES:

THIS APP CAN AND WILL BE USED AS PROOF FOR EVRYTHIG YOU HAVE EVER SAID OR HEARD (ANYTHING SAID OUTSIDE THE APP WILL NEED TO BE PROVED TRUE THROUGH RESEARCH OR THROUGH GENERAL UNDERSTANDING)

IF YOU HAVE THE TIME AND A QUESTION/CONCERN "ASK" 

IF YOU WANT TO GET THINGS DONE MYKAI HAS THE ANSWER

VOTE FOR WHAT YOU BELIEVE IN OR HELP PEOPLE UNDERSTAND HOW YOU FEEL IF YOU DON'T LIKE THE OPTIONS

WORK WITH ONE ANOTHER TO GET WHAT YOU THINK NEEDS TO GET DONE, DONE AS SOON AS POSSIBLE

PEOPLE MYKAI WORKED WITH:



PROFILES:

People can view question matches and chat history without an account. An account is required to post a question or send a chat reply. Create an account with a public name, email, and password, or sign in with an existing email and password.

The Chat page lists saved conversations for the signed-in profile, with the most recent message and a link to reopen each room. A reply from another person is identified in the list.

The profile name and email address are not verified. The name is public; the email is only used to sign in. Passwords are stored as salted PBKDF2 hashes, and browsers use HTTP-only, same-site session cookies that are marked Secure when the site uses HTTPS. There is no password reset yet, so users must save their password safely. Accounts have a 30-day sign-in cookie.

When an existing browser-only profile is upgraded to an account in the same browser, its saved questions and chat history stay connected to the account.

Before allowing other devices or internet users to sign in, put the site behind HTTPS. The built-in development server uses plain HTTP; do not send passwords over a network until HTTPS is configured.

Chat rooms include an experimental audio/video calling prototype for up to four people. Calls use browser WebRTC in a peer-to-peer mesh, so each browser sends media to every other participant; call quality can drop as the group grows. The server only relays call setup messages and does not record call media. Camera and microphone access requires HTTPS (localhost is allowed for local testing). A public STUN server helps browsers find a direct connection, but some networks require a TURN relay; calls are not guaranteed to connect on every network. For larger groups, use a media server (SFU) rather than increasing the prototype limit.

## Running the site

From the project folder, start the server with `python pythonfiles/server.py` and open `http://127.0.0.1:8000`.

Files are grouped by type: website pages are in `htmlfiles`, JavaScript in `javascriptfiles`, stylesheets in `cssfiles`, text files in `textfiles`, the server in `pythonfiles`, and the saved database in `databasefiles`. The server uses these paths while keeping the website URLs unchanged.