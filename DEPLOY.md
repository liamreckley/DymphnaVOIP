# Deploying the Dymphna VoIP backend (GCP)

First-time provisioning of the VoIP/Asterisk stack on the **`dymphna-voip`** VM in the
**`dymphna-infrastructure`** GCP project. Run the `gcloud` commands from Google Cloud
Shell (easiest — no install) or any machine with `gcloud` authed to the project.

```bash
gcloud config set project dymphna-infrastructure
ZONE=$(gcloud compute instances list --filter="name=dymphna-voip" --format="value(zone)")
REGION=${ZONE%-*}
echo "Zone=$ZONE  Region=$REGION"
```

## What you provide
- **voip.ms**: SIP sub-account username/password + a DID. ✅ (you have this)
- **EHR secret**: the EHR's `NEXTAUTH_SECRET` (64 chars, confirmed in `Dymphna EHR/.env`) →
  becomes `JWT_SECRET` on the VM so app login tokens validate.
- **DNS control** for `dymphnacounseling.com` (to add a `voip.` record).

---

## 1. Static IP + DNS  (do first — DNS propagation takes time)
```bash
gcloud compute addresses create dymphna-voip-ip --region="$REGION"
IP=$(gcloud compute addresses describe dymphna-voip-ip --region="$REGION" --format="value(address)")
echo "Static IP: $IP"

# Swap the VM's ephemeral IP for the static one
gcloud compute instances delete-access-config dymphna-voip --zone="$ZONE" --access-config-name="External NAT"
gcloud compute instances add-access-config    dymphna-voip --zone="$ZONE" --access-config-name="External NAT" --address="$IP"
```
Then create an **A record** `voip.dymphnacounseling.com → $IP` wherever you manage
`dymphnacounseling.com` DNS (same place the `ehr.` record lives). Verify:
`dig +short voip.dymphnacounseling.com` returns `$IP`.

## 2. Firewall
```bash
gcloud compute instances add-tags dymphna-voip --zone="$ZONE" --tags=dymphna-voip
gcloud compute firewall-rules create dymphna-voip-web --allow=tcp:80,tcp:443 --target-tags=dymphna-voip --source-ranges=0.0.0.0/0
gcloud compute firewall-rules create dymphna-voip-wss --allow=tcp:8089        --target-tags=dymphna-voip --source-ranges=0.0.0.0/0
gcloud compute firewall-rules create dymphna-voip-rtp --allow=udp:10000-20000 --target-tags=dymphna-voip --source-ranges=0.0.0.0/0
# voip.ms trunk. Safer: restrict --source-ranges to voip.ms server IPs instead of 0.0.0.0/0.
gcloud compute firewall-rules create dymphna-voip-sip --allow=udp:5060        --target-tags=dymphna-voip --source-ranges=0.0.0.0/0
```

## 3. Cloud SQL: VoIP's own database
```bash
gcloud services enable sqladmin.googleapis.com
INSTANCE=$(gcloud sql instances list --format="value(name)" | head -1)   # or set explicitly
CONN=$(gcloud sql instances describe "$INSTANCE" --format="value(connectionName)")
echo "Instance=$INSTANCE  ConnectionName=$CONN"

gcloud sql users     create voip          --instance="$INSTANCE" --password='CHOOSE_A_STRONG_PASSWORD'
gcloud sql databases create dymphna_voip  --instance="$INSTANCE"
# then grant (PG15+): connect to dymphna_voip as an admin and run scripts/infra-db-setup.sql
```

Let the proxy authenticate as the VM's service account:
```bash
SA=$(gcloud compute instances describe dymphna-voip --zone="$ZONE" --format="value(serviceAccounts[0].email)")
gcloud projects add-iam-policy-binding dymphna-infrastructure --member="serviceAccount:$SA" --role="roles/cloudsql.client"
```

## 4. Code + secrets on the VM
```bash
gcloud compute ssh dymphna-voip --zone="$ZONE"
# --- on the VM ---
git clone https://github.com/liamreckley/DymphnaVOIP.git
cd DymphnaVOIP
cp .env.example .env
nano .env     # fill in:
#   INSTANCE_CONNECTION_NAME = <CONN from step 3>
#   DATABASE_URL = postgresql+asyncpg://voip:<password>@cloud-sql-proxy:5432/dymphna_voip
#   JWT_SECRET   = <EHR NEXTAUTH_SECRET>
#   VOIPMS_SIP_USERNAME / VOIPMS_SIP_PASSWORD / VOIPMS_DID  (+ VOIPMS_API_* if used)
#   LETSENCRYPT_HOST / VIRTUAL_HOST already default to voip.dymphnacounseling.com
```
> Use a fresh GitHub token or a deploy key to clone — **not** the one currently embedded
> in the repo's git config (rotate that; it's exposed).

## 5. Bring it up
```bash
./scripts/vm-setup.sh          # installs Docker + compose, then docker compose up -d --build
sudo docker compose logs -f acme-companion   # watch the TLS cert issue (needs DNS + :80 live)
```

## 6. Validate
```bash
sudo docker compose ps                                              # all services Up
sudo docker compose exec asterisk asterisk -rx "http show status"   # TLS @ 0.0.0.0:8089
sudo docker compose exec asterisk asterisk -rx "pjsip show transports"   # transport-wss present
curl https://voip.dymphnacounseling.com/voip/health                 # {"status":"ok"}
# from your laptop — wss reachable:
npx wscat -c "wss://voip.dymphnacounseling.com:8089/ws"
```
If `http show status` shows no TLS: check the cert mounted readable at
`sudo docker compose exec asterisk ls -l /etc/asterisk/keys/`.

## 7. voip.ms trunk (for real calls)
In the voip.ms portal: point your **DID → the SIP sub-account** used in `.env`, and confirm
the trunk registers: `sudo docker compose exec asterisk asterisk -rx "pjsip show registrations"`.

---

### Notes
- **Cert renewal**: acme-companion auto-renews; Asterisk picks up the new cert on restart —
  a monthly `docker compose restart asterisk` (cron) is enough.
- **TURN**: for reliable audio on cellular, run coturn and set `TURN_URL/USERNAME/PASSWORD`
  in `.env` — they flow to the app automatically via `/voip/sip/credentials`.
- **Extensions**: created per counselor via the API (`POST /voip/extensions`) once the EHR
  can issue an admin `voip_token` — that's the next milestone after this is up.
