# BIZKHATA – Mobile app + Web link (Play Store tak ki poori guide)

## Kaise kaam karta hai

```
 Dukandar ka phone                         Dukandar ka browser / laptop
  Android app (Play Store)                  https://aap-ka-domain
          \                                      /
           \______  ek hi server + database ____/
                  (Python backend, har dukan ka alag database)
```
* **Website** (`https://aap-ka-domain`): dukandar aur admin dono. Dukandar yahan se register/login kar sakta hai.
* **Android app**: sirf **dukandar wali side** (wohi 5 tabs, Receivable/Payable Entry, report, backup, bill ki slip). **Admin panel app mein nahi chalta**: admin ID se login karne par likh kar aata hai "ایڈمن پینل صرف ویب سائٹ پر چلتا ہے". Admin sirf website se.
* Dukan jahan bhi register ho (website ya app), **dono jagah ek hi account chalta hai**: same mobile number + password.
* Website update karen to app mein khud update aa jata hai (Play Store par dobara upload sirf tab chahiye jab icon, naam ya package badalna ho).
* iPhone walon ke liye: Safari mein website kholen > Share > **Add to Home Screen** (PWA).
* Android par bhi bina Play Store ke: Chrome mein website kholen > menu > **Install app** (login page par "ایپ انسٹال کریں" ka link bhi aata hai).

## Is mein kya kya diya gaya hai

| Cheez | Kahan |
|---|---|
| Installable web app (PWA): `manifest.webmanifest`, `sw.js`, icons, offline page | `bizkhata-python-backend.zip` > `public/` |
| Android Studio project (Trusted Web Activity) | `bizkhata-android-app.zip` |
| Play Store assets: 512 icon, 1024x500 feature graphic, 6 screenshots (1080x1920), listing text | `bizkhata-play-store-assets.zip` |
| Privacy policy page `/privacy`, account delete page `/delete-account` | backend `public/` (Play Store ke liye lazmi) |
| In-app **Delete account** (menu ⋮) | app/website dono mein |
| `/.well-known/assetlinks.json` (server khud banata hai `.env` se) | backend |

## Step 1 – Website live karen
`README_DEPLOY.md` ke mutabiq backend HTTPS par live karen. Check: `https://aap-ka-domain/api/health`, `/manifest.webmanifest`, `/privacy` teeno khulne chahiye.

## Step 2 – `.env` mein app ki settings
```
ANDROID_PACKAGE=com.bizease.bizkhata
ANDROID_SHA256=            # Step 4 mein milega
PLAY_STORE_URL=            # app live hone ke baad link; tab website par "Get the Android app" link aa jata hai
APP_ALLOW_PAYMENT=1        # niche "Payment ka qaida" dekhen
```
Phir `sudo systemctl restart bizkhata`.

## Step 3 – Android app (.aab) banayen (3 tareeqe, koi ek)

**A) PWABuilder (sab se aasan, coding nahi)**
1. https://www.pwabuilder.com > apna `https://aap-ka-domain` daalen > Start.
2. **Package for stores > Android > Google Play**.
3. Package ID: `com.bizease.bizkhata`, App name: `BIZKHATA`, Start URL: `/?app=1`, "Signing key": **Create new** (download hone wali zip mein `.aab`, `signing.keystore` aur passwords hote hain: **sambhal kar rakhen**).
4. Download hui `.aab` Play Console mein upload hogi.

**B) Android Studio project (`bizkhata-android-app.zip`)**: us ke `README.md` ke steps.

**C) Bubblewrap (command line)**: `npm i -g @bubblewrap/cli` > `bubblewrap init --manifest=https://aap-ka-domain/manifest.webmanifest` > `bubblewrap build`.

## Step 4 – Digital Asset Links (app ko bar ke baghair kholne ke liye)
1. Play Console mein app banane ke baad: **Release > Setup > App signing (App integrity)** se **SHA-256 certificate fingerprint** copy karen (App signing key wali; local test build ke liye apni upload key ka SHA-256 bhi: `keytool -list -v -keystore bizkhata.jks`).
2. Server `.env`: `ANDROID_SHA256=AA:BB:...:ZZ` (kai fingerprints comma se).
3. Restart karen aur check: `https://aap-ka-domain/.well-known/assetlinks.json` mein aap ka package aur fingerprint nazar aaye.
4. Agar app ke upar browser ki bar nazar aaye to matlab fingerprint ya package match nahi kar raha.

## Step 5 – Google Play Console
1. https://play.google.com/console par developer account (one-time **USD 25**). Naye personal accounts ko production se pehle kuch din / kuch testers ke saath **closed testing** karni parti hai; organization account ke liye business verification (D-U-N-S). Rules badalte rehte hain, Play Console ki screen follow karen.
2. **Create app**: naam `BIZKHATA`, Free, App (not game).
3. Store listing: `bizkhata-play-store-assets.zip` ka text (`PLAYSTORE_LISTING.md`), icon 512, feature graphic, screenshots.
4. App content: **Privacy policy** = `https://aap-ka-domain/privacy`. **Account deletion URL** = `https://aap-ka-domain/delete-account`. Data safety form ke jawab `PLAYSTORE_LISTING.md` mein diye hain. Target age: 18+. Category: Business.
5. Production (ya pehle testing) > Create release > `.aab` upload > Review > Roll out.
6. Review mein aam tor par kuch din lagte hain.

## Payment ka qaida (zaroor parhen)
Dukandar app mein bank slip upload kar ke subscription ada karta hai (jaisa aap ne kaha). Google Play ki payments policy aam tor par app ke andar digital service / subscription ke liye **Google Play Billing** mangti hai; bank transfer slip wala tareeqa review mein objection par reject ho sakta hai. Do rastay:
* `APP_ALLOW_PAYMENT=1` (default): app mein "Pay" aur slip upload chalta hai. Agar Google objection kare to:
* `APP_ALLOW_PAYMENT=0`: Android app mein "Pay" ki jagah **"ویب سائٹ پر ادا کریں"** ka button aata hai jo website kholta hai; slip upload website par hota hai, app mein sirf bills nazar aate hain. Website par koi farq nahi parta. Server restart ke baad foran lagu, app dobara upload nahi karni.
Policy ki taaza tafseel Play Console / Google ki official policy page par dekh len; ye qanooni salah nahi.

## Test checklist (live karne se pehle)
1. Website par register > entries > report > Excel export.
2. Usi account se Android app mein login: wohi data nazar aaye.
3. App mein naya shop register karen > website par usi mobile se login ho jaye.
4. App mein admin ID se login: "admin panel sirf web par" ka paigham.
5. Bill: slip upload (camera / gallery) > admin website par approve > app mein ID active.
6. Menu > Delete account (naya test account par) > dobara login na ho.
