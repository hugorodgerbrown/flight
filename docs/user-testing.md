# Testing Flight as a user

A script for checking a deployment from start to finish, the way a new
user meets it. You need no technical knowledge: a phone or computer, an
email address you can read, and about 30 minutes (plus a Claude account
for the last part).

Work through the scenarios in order. Each one says what to do and what you
should see. When something differs, note the scenario number, what you
did, what you saw, and take a screenshot.

**Before you start**, ask whoever deployed it for:

- the web address of the site (below, `https://example.com`);
- an email address that has never been used on the site, for scenario 2;
- confirmation that your account is allowed to connect Claude (scenario 9).
  New accounts can't, until someone running the site turns it on for you.

## 1. First visit

1. Open `https://example.com` in your browser.
2. Read the home page, then follow **Terms**, **Privacy** and **Help** at
   the bottom of the page.

You should see: a home page that says what Flight is, a
**Get started** button, and three pages that open without signing in. The
privacy page says what is kept about you.

## 2. Create an account

1. Press **Sign in** at the top of the home page.
2. Enter the email address that has never been used here, and press
   **Email me a link**.
3. A page titled **Check your email** appears. Find the email: its subject
   is "Your one-time Flight verification code:" followed by six digits.
4. Type the six digits into **Code** and press **Sign in**.

You should see: the email arrives within a minute (check spam), and after
the code you land in the app on its home page, **Ask Claude where your flight is**. There was no password
to choose: the same email both creates the account and signs in.

## 3. Sign out, and back in with the link

1. Press **Account** at the top, then **Sign out**.
2. Sign in again with the same email, but this time open the **link** in
   the email instead of typing the code.
3. On the page the link opens, press **Continue**.

You should see: you're back on the app's home page, as the same person.

## 4. Mistakes and expiry

1. Sign out, request a new email, and type a wrong code.
   You should see: "That code didn't work. Check the newest email, or use
   its link."
2. Now type the right code. You should be signed in.
3. Open the link from that same email again.
   You should see: a page headed "This link has expired". A link works
   once, and only for 15 minutes.
4. Request three or four emails in a row, then use the code from an older
   one. Only the newest email's code should work.

## 5. Add a passkey

A passkey lets you sign in with Face ID, a fingerprint or your device PIN
instead of waiting for an email.

1. Go to **Account** and press **Add a passkey**. Follow your device's
   prompt.
2. Sign out. On the sign-in page, press **Sign in with a passkey**.

You should see: the passkey listed on **Account** with the date it was added,
and signing in with it takes no email. Try **Remove** on it afterwards: it
disappears from the list and no longer signs you in.

## 6. Install the app and use it offline

1. Install it: on iPhone or iPad, open the site in Safari, tap **Share**,
   then **Add to Home Screen**. On Android or a computer, use **Install** in
   the browser's menu.
2. Open it from the home screen. You should see a brief launch screen in
   the app's colour, then the app's home page. You may need to sign in again inside
   the app on iPhone: type the code rather than opening the link.
3. Turn on airplane mode (or turn off Wi-Fi), then close and reopen the app.

You should see: with no connection the app still opens on its home page,
with a yellow bar saying you're offline.

## 7. Signing out on a shared device

1. In the installed app, go to **Account** and **Sign out**.
2. Turn off the connection and open the app again.

You should see: the sign-in page, not the app's home. A signed-out app
must not show the last person's pages, even offline.

## 8. Connect Claude

Flight lets Claude tell you where a flight is, and answer questions about
the site.

1. In Claude (claude.ai or the Claude app), open **Settings**, then
   **Connectors**, and add a custom connector with the URL
   `https://example.com/mcp`.
2. Press **Connect**. A Flight page opens: sign in with your
   email and code if asked.
3. A page asks "Connect Claude?". Press **Connect**.

You should see: Claude says the connector is connected. If the page says
"This connection can't go ahead" or you get a "forbidden" error, your
account isn't allowed to connect yet: ask whoever runs the site.

## 9. Talk to Flight through Claude

Start a new chat in Claude with the connector turned on and try these.
Claude may ask permission before it uses the connector each time: allow it.

| Ask Claude | You should see |
| --- | --- |
| "Where is BA117?" (or any flight in the air now) | A sentence saying where it is, and a map card: its route, where it is now and when it's due. |
| "When does EZY8461 land?" | When it's due, or that it has landed. |
| "What does Flight keep about me?" | A summary of the privacy page, in Claude's words. |
| "What are Flight's terms of service?" | A summary of the terms page. |
| "How do I sign in to Flight on my iPhone?" | Advice from the help page: type the code rather than opening the link. |
| "Where is XX0000?" | Claude says Flightradar24 has no such flight, and suggests the operating airline's number. |

## 10. Disconnect Claude

1. Visit `https://example.com/oauth/connected/` while signed in.
2. Press **Disconnect** next to Claude.
3. In Claude, ask "Where is BA117?" again.

You should see: Claude listed under **Connected apps** before you
disconnect, and the list empty afterwards. Claude can no longer use
Flight; it asks you to connect again.

## When you're done

Send whoever asked you to test: the scenario numbers that passed, and for
each one that didn't, what you did, what you saw, and a screenshot. Note
your device and browser (for example "iPhone 15, Safari, installed app").
