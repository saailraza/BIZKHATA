# BIZKHATA ko apne subdomain par live karne ki poori guide (Hostinger + Vercel + GitHub + database)

Aap ke screenshots ke mutabiq: project Vercel par hai (`bizkhata-eight.vercel.app`), code GitHub par hai, aur domain `bizeasesolutions.online` ka DNS Hostinger mein hai.

---

## 0. Pehle ye 3 baatein samajh len

1. **Vercel par abhi sirf website ki file (login page) chal rahi hai.** Agar wo "standalone" single-HTML file hai to har user ka data **sirf us ke apne browser mein** rehta hai. Asli users ke liye ye kaafi nahi: aap ko **backend + PostgreSQL** chahiye. Wohi is guide mein live hota hai.
2. **Database GitHub par nahi dala jata.** GitHub sirf **code** ke liye hai (private repository rakhen). Database mein users ke passwords, entries aur slips hote hain: unhein GitHub par daalna data leak hai, aur GitHub database chalata bhi nahi. Database **server par PostgreSQL** mein rehta hai, aur har dukan ka **alag database** registration par khud ban jata hai.
3. **"Har dukan ka alag database" ke liye PostgreSQL ko naya database banane ki ijazat chahiye.** Ye **VPS** par hota hai (Hostinger VPS). Vercel (serverless) aur Hostinger ki normal shared / web hosting par nahi hota.

### Do raste

| | **Raasta A (recommended)** | Raasta B |
|---|---|---|
| Website | Hostinger VPS par (backend khud serve karta hai) | Vercel par |
| Backend + database | Hostinger VPS | Hostinger VPS (alag `api.` subdomain) |
| Subdomains | 1: `khata.bizeasesolutions.online` | 2: `khata.` (Vercel) + `api.` (VPS) |
| Mushkil | Aasan, sab ek jagah | Do jagah sambhalna, API Vercel se guzarti hai (size limits / extra delay) |
| Android app / PWA baad mein | Seedha chalta hai | Chalta hai, lekin zyada jhanjhat |

**Aap raasta A rakhen.** Vercel ka project phir zaroori nahi (chahen to rehne den ya delete kar den).

---

## 1. Hostinger VPS lein

1. Hostinger hPanel > **VPS** > plan chunen (KVM 1 ya KVM 2; **kam az kam 2 GB RAM**, 4 GB behtar). Qeemat Hostinger ki site par dekh len.
2. **Operating system: Ubuntu 24.04 (plain, koi panel nahi)**. Root password set karen.
3. Setup ke baad hPanel > VPS > **Overview** mein server ka **IP address** (jaise `123.45.67.89`) likh len.

## 2. Subdomain ko VPS ka IP den (aap ke screenshot wala DNS page)

hPanel > Domains > `bizeasesolutions.online` > **DNS / Nameservers**. Upar "Add Record" wali row mein:

| Type | Name | Value (Points to) | TTL |
|---|---|---|---|
| **A** | `khata` | VPS ka IP (jaise `123.45.67.89`) | `300` |

"Add Record" dabayen. Neeche jo purane records hain (`hostingermail-a/b/c._domainkey` CNAME, MX, SPF/TXT) **unhein bilkul na chheren**: wo aap ki email ke hain.
Check karen (kuch minute baad): Windows par CMD mein `nslookup khata.bizeasesolutions.online`; jawab mein aap ka VPS IP aana chahiye.

> Agar `khata` naam ka koi purana record pehle se ho (CNAME ya A), usay pehle delete ya edit karen, warna dono chalte nahi.

## 3. Code server par pohanchayen

**Tareeqa 1 – GitHub (update karna aasan, recommended)**
1. GitHub par **naya Private repository** banayen, naam `bizkhata-server`.
2. `bizkhata-python-backend.zip` apne PC par khol kar andar ke **sab files** repo mein upload karen (GitHub > Add file > Upload files; folder ke andar ki files/folders, `.env` kabhi nahi: wo hai hi nahi, sirf `.env.example` hai).
3. Server par private repo ke liye **Deploy key**: server par `ssh-keygen -t ed25519 -N "" -f ~/.ssh/bk_deploy && cat ~/.ssh/bk_deploy.pub` chalayen; jo text aaye usay GitHub repo > Settings > **Deploy keys** > Add (Read-only). Phir:
   ```bash
   apt update && apt install -y git
   GIT_SSH_COMMAND="ssh -i ~/.ssh/bk_deploy -o StrictHostKeyChecking=accept-new" git clone git@github.com:AAPKA-USERNAME/bizkhata-server.git /opt/bizkhata
   git -C /opt/bizkhata config core.sshCommand "ssh -i /root/.ssh/bk_deploy"
   ```

**Tareeqa 2 – seedha upload (GitHub ke baghair)**
Apne PC se (Windows par WinSCP / FileZilla, ya `scp`): `scp bizkhata-python-backend.zip root@VPS-IP:/root/` phir server par:
```bash
apt update && apt install -y unzip && unzip /root/bizkhata-python-backend.zip -d /opt    # /opt/bizkhata ban jata hai
```

Server mein jane ke liye: hPanel > VPS > **Browser terminal**, ya apne PC se `ssh root@VPS-IP`.

## 4. Ek command se sab install

```bash
sudo bash /opt/bizkhata/deploy/install.sh khata.bizeasesolutions.online info@bizeasesolutions.online
```
Ye khud karta hai: PostgreSQL + Nginx + Python install, database user (`CREATEDB` ke saath), master database, random `SECRET` aur admin password ki `.env`, app ko service banana (server restart par khud chale), firewall, **free HTTPS (Let's Encrypt)**, aur roz raat 02:30 ka **backup** (master + har dukan ka alag).

Aakhir mein screen par **admin ka password** likh kar aata hai: **usay abhi copy kar len.**

## 5. Check karen

1. Browser: `https://khata.bizeasesolutions.online/api/health` > `{"ok":true,...}`
2. `https://khata.bizeasesolutions.online` > login page.
3. Login: `admin` + wohi password jo install ke aakhir mein aaya.
4. **Settings** mein: monthly fee (999), **bank account ki details** (dukandar ko payment ke liye dikhti hain), WhatsApp number, aur **admin ka naya password**.
5. Naye browser (ya phone) se ek test dukan register karen > entries > report > bill ki slip > admin se approve.

## 5b. Test ki fixed ID (`biztest`)

`.env` mein `TEST_USER=1` ho (install ke baad by default hota hai) to server ek **fixed test dukan** bana deta hai:

* Login: **`biztest`**   Password: **`123456`**
* Ye ID hamesha active rehti hai (trial khatam nahi hota, bill nahi banta) aur **har browser / phone par wohi account aur wohi data** nazar aata hai, to baar baar register nahi karna parta.
* Admin panel mein ye "Test Shop" ke naam se nazar aati hai.
* **Asli users aane se pehle** `.env` mein `TEST_USER=0` karen, `sudo systemctl restart bizkhata`, aur admin panel se "Test Shop" delete kar den (warna koi bhi `biztest / 123456` se login kar sakta hai).

## 6. Database kahan hai aur kaise dekhen

* Server par PostgreSQL mein. Master database: `bizkhata_master` (admins, dukanon ki list, users, bills, slips).
* **Har dukan ka alag database:** naam `bk_<dukan ki id>`. List: `sudo -u postgres psql -l`
* Kisi dukan ke database ko dekhna: `sudo -u postgres psql -d bk_xxxxxxxx` phir `\dt`, `SELECT * FROM sales;`
* Admin panel se company delete karen to uska database bhi delete ho jata hai.
* GitHub par database **kabhi nahi**. Backup files `/var/backups/bizkhata/<tareekh>/` mein hoti hain: inhein kabhi kabhi apne PC / Google Drive par bhi utaar len (`scp -r root@VPS-IP:/var/backups/bizkhata .`). Hostinger VPS ke snapshot / backup option ka bhi faida len.

## 7. Code badalne par update

1. Changes GitHub par push / upload karen.
2. Server par: `sudo bash /opt/bizkhata/deploy/update.sh`
(Dukandaron ke data ko kuch nahi hota; app 2-3 second mein restart hoti hai.)

## 8. Vercel project ka kya karen

* **Raasta A (recommended):** Vercel ki zaroorat nahi. Chahen to purani `bizkhata-eight.vercel.app` ko band kar dein, taake log purane (data-browser-mein-rehne-wale) page par na jayen: Vercel > Project > Settings > **Delete Project**. (Ya Settings > Domains se hata den.)
* **Agar phir bhi Vercel par website rakhni ho (Raasta B):**
  1. VPS par install `api.` ke naam se: DNS mein A record `api` > VPS IP, aur `sudo bash deploy/install.sh api.bizeasesolutions.online info@bizeasesolutions.online`.
  2. GitHub ke Vercel wale repo mein `bizkhata-vercel-frontend.zip` ki files daalen (index.html, assets, manifest, sw.js, vercel.json...). `vercel.json` mein `api.bizeasesolutions.online` pehle se likha hai; apna domain ho to badal den.
  3. Vercel > Project > **Settings > Domains > Add** > `khata.bizeasesolutions.online`. Vercel jo record dikhaye (aam tor par **CNAME**, Name `khata`, Value `cname.vercel-dns.com` ya jo Vercel likhe) wohi Hostinger DNS mein add karen. Verified hone par HTTPS khud lag jata hai.
  4. Mushkil: sab API calls Vercel se guzarti hain; badi files (backup import) par Vercel ki request-size limit lag sakti hai. Is liye A behtar hai.

## 9. Live karne se pehle checklist

- [ ] `https://khata.…/api/health` theek
- [ ] Admin ka naya password, Settings mein fee + bank details + WhatsApp
- [ ] Test dukan: register > entry > report > Excel export > backup import
- [ ] Test dukan: bill ki slip > admin approve > ID active
- [ ] Test: "Password bhool gaye" > admin approve
- [ ] Nightly backup: `ls /var/backups/bizkhata` (agli subah check)
- [ ] `https://` (taala nishan) dikhe, `http://` khud `https://` par jaye
- [ ] Dukandaron ko link den: `https://khata.bizeasesolutions.online`

## 10. Masle aur hal

| Masla | Hal |
|---|---|
| install ke aakhir mein "points to ... but this server is ..." | DNS ka A record abhi nahi laga / purana hai. Sahi karen, 5-10 minute ruken, phir `certbot --nginx -d khata.bizeasesolutions.online -m info@bizeasesolutions.online --agree-tos --redirect` |
| Site nahi khulti, 502 | `systemctl status bizkhata`, `journalctl -u bizkhata -n 50` |
| "permission denied to create database" | `sudo -u postgres psql -c "ALTER USER bizkhata CREATEDB;"` phir `systemctl restart bizkhata` |
| "too many connections" | zyada dukanen: `max_connections` barhayen ya RAM wala plan len |
| Admin password bhool gaye | `.env` mein naya `ADMIN_PASSWORD` nahi chalta (sirf pehli baar). Server par: `cd /opt/bizkhata && sudo -u bizkhata ./venv/bin/python - <<< "from bizkhata import db,security;db.init_master();db.master.execute('UPDATE admins SET password_hash=\$1',[security.hash_password('NAYA-PASSWORD')])"` |
| Dukandar ka password reset | Admin > Approvals > Password reset (pehle call kar ke confirm karen) |
| Server ka time | app khud `Asia/Karachi` istemal karti hai |
| Slip / backup upload nahi hoti | Nginx `client_max_body_size 10m;` (pehle se lagi hai) |

## 11. Zaroori hifazat

* Admin password mazboot; `.env` aur database kisi ko na den; GitHub repo **private**.
* Firewall (install khud lagata hai): sirf 22, 80, 443 khule.
* Mahine mein ek dafa: `apt update && apt upgrade -y`.
* Android app / Play Store baad mein jodni ho to `APP_GUIDE.md` dekhen: backend wohi rehta hai, kuch dobara nahi banana.
