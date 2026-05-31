# Deploying the Dymphna VoIP backend (GCP)

This reflects the **validated** deploy on the `dymphna` VM in the `dymphna-infrastructure`
project (Asterisk + FastAPI + nginx/Let's Encrypt, talking to the shared Cloud SQL).
Run `gcloud` from **Cloud Shell** (you're the project owner there — the VM's own service
account has limited scopes and will deny these).

```bash
gcloud config set project dymphna-infrastructure
ZONE=us-central1-a            # the dymphna VM's zone
```

## What you provide
- **voip.ms**: SIP sub-account user/pass + a DID.
- **EHR secret**: the EHR's `NEXTAUTH_SECRET` → `JWT_SECRET` (so app login tokens validate).
- **DNS** for `dymphnacounseling.com` (to point `voip.` at the VM).

## 1. Static IP + DNS  (DNS first — it propagates)
```bash
# Promote the VM's current IP to static (no downtime):
IP=$(gcloud compute instances describe dymphna --zone="$ZONE" --format="value(networkInterfaces[0].accessConfigs[0].natIP)")
gcloud compute addresses create dymphna-ip --addresses="$IP" --region="${ZONE%-*}"
echo "Static IP: $IP"
```
Create an **A record** `voip.dymphnacounseling.com → $IP`. Verify: `dig +short voip.dymphnacounseling.com`.

## 2. Firewall
```bash
gcloud compute instances add-tags dymphna --zone="$ZONE" --tags=dymphna-voip
gcloud compute firewall-rules create dymphna-voip-web --allow=tcp:80,tcp:443      --target-tags=dymphna-voip --source-ranges=0.0.0.0/0
gcloud compute firewall-rules create dymphna-voip-wss --allow=tcp:8089            --target-tags=dymphna-voip --source-ranges=0.0.0.0/0
gcloud compute firewall-rules create dymphna-voip-rtp --allow=udp:10000-20000     --target-tags=dymphna-voip --source-ranges=0.0.0.0/0
# voip.ms trunk — HARDEN: restrict --source-ranges to voip.ms server IPs, not 0.0.0.0/0
gcloud compute firewall-rules create dymphna-voip-sip --allow=udp:5060            --target-tags=dymphna-voip --source-ranges=0.0.0.0/0
```

## 3. Cloud SQL: VoIP's own database
The shared instance is `dymphna-infrastructure` (Postgres 15). Note its **PRIVATE_ADDRESS** —
the VM connects to it directly over the VPC (no proxy needed):
```bash
gcloud sql instances list   # note PRIVATE_ADDRESS (e.g. 10.24.208.6)
gcloud sql users     create voip          --instance=dymphna-infrastructure --password='STRONG_PW'
gcloud sql databases create dymphna_voip  --instance=dymphna-infrastructure
```
Then make `voip` own its DB so it can create tables (PG15). Easiest from the VM once psql is
installed (`sudo apt-get install -y postgresql-client`), connecting as `postgres`:
```sql
GRANT voip TO postgres;
ALTER DATABASE dymphna_voip OWNER TO voip;
```
> We do **not** use the Cloud SQL Auth Proxy: it needs the VM to have the `cloud-platform`
> access scope, which the default scopes lack (`ACCESS_TOKEN_SCOPE_INSUFFICIENT`). Direct
> private-IP is simpler and stays on the VPC.

## 4. Code + `.env` on the VM
```bash
gcloud compute ssh dymphna --zone="$ZONE"     # or the Console "SSH" button
# --- on the VM ---
sudo apt-get install -y git
git clone https://github.com/liamreckley/DymphnaVOIP.git && cd DymphnaVOIP
cp .env.example .env && nano .env             # fill in:
#   DATABASE_URL = postgresql+asyncpg://voip:STRONG_PW@<PRIVATE_ADDRESS>:5432/dymphna_voip
#   JWT_SECRET   = <EHR NEXTAUTH_SECRET>
#   ASTERISK_SECRET = <any strong value>      (Asterisk + API share this one)
#   VOIPMS_SIP_USERNAME / VOIPMS_SIP_PASSWORD / VOIPMS_DID
```

## 5. Bring it up
```bash
bash scripts/vm-setup.sh                       # installs Docker, builds, starts
sudo docker compose logs -f acme-companion     # watch the TLS cert issue
```

## 6. Validate (from anywhere)
```bash
curl https://voip.dymphnacounseling.com/voip/health        # {"status":"ok",...}
sudo docker compose exec asterisk asterisk -rx "pjsip show transports"   # transport-wss present
sudo docker compose exec asterisk asterisk -rx "manager show connected"  # AMI auth OK (no errors)
# externally: the wss port answers an upgrade
curl -o /dev/null -w "%{http_code}\n" https://voip.dymphnacounseling.com:8089/ws   # 426
```

## 7. voip.ms trunk (for real calls)
Point your **DID → the SIP sub-account** in `.env`, then check it registered:
`sudo docker compose exec asterisk asterisk -rx "pjsip show registrations"`.

---

## Gotchas we hit (so you don't again)
- **Run gcloud admin commands in Cloud Shell**, not on the VM (the VM's service account is
  scope-limited and denies stop/start/set-service-account).
- **Asterisk image is `andrius/asterisk:22`** (Debian) — there is no `:22-alpine`.
- **Cloud SQL `postgres` isn't a true superuser** — `CREATE DATABASE ... OWNER voip` needs
  `GRANT voip TO postgres` first.
- **If table creation errors with "voip_extensions already exists"** from a half-finished run:
  wipe + rebuild — `psql ... -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public AUTHORIZATION voip;"`
  then `docker compose up -d voip-api`.
- Per-extension PJSIP config is a **directory-mounted volume** (`/etc/asterisk/pjsip_ext`);
  mounting a named volume onto a single file path silently turns it into a directory and breaks
  the `#include`.
