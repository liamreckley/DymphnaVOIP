from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    # Database
    database_url: str = 'postgresql+asyncpg://voip:voip@localhost:5432/dymphna_voip'

    # Redis
    redis_url: str = 'redis://localhost:6379/0'

    # JWT (shared secret with EHR — must match EHR NEXTAUTH_SECRET)
    jwt_secret: str = 'change-me-in-production'
    jwt_algorithm: str = 'HS256'

    # Asterisk AMI
    asterisk_host: str = 'asterisk'
    asterisk_port: int = 5038
    asterisk_username: str = 'dymphna_ami'
    asterisk_secret: str = 'change-me'

    # Asterisk dynamic extension config (writable path)
    pjsip_extensions_path: str = '/etc/asterisk/pjsip_extensions.conf'

    # VoIP.ms REST API
    voipms_api_username: str = ''
    voipms_api_password: str = ''
    voipms_did: str = ''
    voipms_base_url: str = 'https://voip.ms/api/v1/rest.php'

    # VoIP.ms SIP trunk credentials (separate from API creds — create sub-account in portal)
    voipms_sip_username: str = ''      # e.g. 12345678_dymphna
    voipms_sip_password: str = ''

    # Inbound SMS webhook token (set in VoIP.ms portal → DID → SMS URL as ?token=XXX)
    voipms_webhook_token: str = ''

    # S3 (recordings)
    s3_bucket: str = 'dymphna-voip-recordings'
    aws_region: str = 'us-east-1'

    # Apple VoIP push (PushKit)
    apns_key_id: str = ''
    apns_team_id: str = ''
    apns_key_path: str = '/secrets/apns_voip.p8'
    apns_bundle_id: str = 'com.dymphna.counseling'
    apns_use_sandbox: bool = False

    # FCM (Android push)
    fcm_server_key: str = ''

    # Allowed CORS origins (comma-separated)
    cors_origins: str = 'https://ehr.dymphnacounseling.com'


settings = Settings()
