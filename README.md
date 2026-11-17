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

Questions submitted on Ask or created on Ask Mykai are public, including their descriptions and badges. Chat and Ask Mykai let visitors choose a major badge and optional minor badges to find matching public questions, then open a question to read its description and join its room. Do not include private information in a public question or description.

Profile names are public. Email addresses are private and used for sign-in and verification QR delivery. Passwords are stored as salted PBKDF2 hashes, and browsers use HTTP-only, same-site session cookies that are marked Secure when the site uses HTTPS. There is no password reset yet, so users must save their password safely. Accounts have a 30-day sign-in cookie.

When an existing browser-only profile is upgraded to an account in the same browser, its saved questions and chat history stay connected to the account.

### Member verification

The server reads `verified.txt` as its member roster. Each account receives a number; an entry such as `New Member 6` is unverified, and a trailing `#` marks an approved member. The file is not served to visitors.

On signup, the site still emails a one-time verification QR to the account email; it expires after 24 hours. The simpler option is to show the member's Profile QR. When Mykai's verified account (#5) scans an unverified member's profile, it can explicitly approve them there. Only #5 can verify accounts, and a scan never verifies someone without that explicit action. This is a manual approval badge, not proof of legal identity.

The **Profile** page shows a shareable account QR and can open the camera to scan another member's code. Scanning while signed in adds both accounts to each other's private contact lists immediately. If the verified Mykai account (#5) scans an unverified member's QR, the page also offers a separate **Verify this member** action; adding a contact alone never verifies an account. Camera scanning requires HTTPS and browser camera permission; QR decoding uses a local bundled library, so camera frames are not sent to an external service.

Configure SMTP before enabling new account signups:

1. Copy `.env.example` to `.env` on the hosting computer.
2. Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_FROM` to your email provider's SMTP settings. Keep `.env` private; it is ignored by Git.
3. Keep `PUBLIC_BASE_URL` set to the HTTPS website address.

An unverified signed-in account can use **Send another verification QR** if its code expires.

Before allowing other devices or internet users to sign in, put the site behind HTTPS. The built-in development server uses plain HTTP; do not send passwords over a network until HTTPS is configured.

Chat rooms include an experimental audio/video calling prototype for up to four people. Calls use browser WebRTC in a peer-to-peer mesh, so each browser sends media to every other participant; call quality can drop as the group grows. The server only relays call setup messages and does not record call media. Camera and microphone access requires HTTPS (localhost is allowed for local testing). A public STUN server helps browsers find a direct connection, but some networks require a TURN relay; calls are not guaranteed to connect on every network. For larger groups, use a media server (SFU) rather than increasing the prototype limit.

## GitHub Pages preview

GitHub Pages can show a static preview of the site, but it cannot run the Python server. The preview includes the home, ask, chat, about, Ask Mykai, and profile pages with their shared stylesheet. Account, contact, question, room, and chat features are unavailable there, and form submissions are disabled. The database and server are not published.

To publish the preview:

1. Push this repository to GitHub.
2. In the repository, open **Settings > Pages** and set the build and deployment source to **GitHub Actions**.
3. Open the **Actions** tab and wait for **Publish GitHub Pages preview** to finish. The workflow runs on pushes and can also be started manually.

The deployed address will appear in the workflow run and under **Settings > Pages**. Run the Python server locally to use the full website.

## Start the full website

On the Windows computer that hosts the site, open PowerShell in this repository and install the server dependencies:

```powershell
python -m pip install -r requirements.txt
```

To run the verification tests, install the test dependencies and run:

```powershell
python -m pip install -r requirements-test.txt
python -m unittest discover -s tests -v
```

Then start the website and its Cloudflare Tunnel:

```powershell
python startup.py
```

This starts the Python website and its Cloudflare Tunnel. Keep the PowerShell window open while people use the site; press **Ctrl+C** to stop both. The computer must stay on and connected to the internet.