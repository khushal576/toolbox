# AWS KMS – 2. Envelope encryption, operations, rotation, multi-Region and key stores

Short notes. Each point is a fact you can be asked about.

## A. Envelope encryption (core exam idea)
- **Why**: KMS `Encrypt` handles only **4,096 bytes**. Big data is encrypted locally with a **data key**; the **data key is encrypted by the KMS key**.
- **Encrypt flow**: call `GenerateDataKey` → KMS returns **plaintext data key + encrypted data key** → encrypt data locally with the plaintext key → **discard the plaintext key** → store **ciphertext + encrypted data key** together.
- **Decrypt flow**: call `Decrypt` on the encrypted data key → get plaintext key → decrypt data locally. The ciphertext blob includes key metadata so KMS finds the right KMS key (and key material version).
- **Benefits**: only small keys cross the network; data stays local; each object can have its own data key; supports data larger than 4 KB.
- **Operations**:
  - `Encrypt` / `Decrypt` – direct, ≤ 4,096 bytes.
  - `GenerateDataKey` – plaintext + encrypted copy.
  - `GenerateDataKeyWithoutPlaintext` – encrypted copy only (use later).
  - `GenerateDataKeyPair` / `...WithoutPlaintext` – asymmetric data key pairs.
  - `ReEncrypt` – decrypt and re-encrypt under another key **inside KMS** (plaintext never leaves).
  - `GenerateRandom` – random bytes from HSM.
  - `Sign` / `Verify`, `GenerateMac` / `VerifyMac`.
  - `GetPublicKey` – download the public key (asymmetric).
- **Data key caching** (AWS Encryption SDK) reduces KMS calls and cost; trade-off: reuse of one data key for many messages.
- **Encryption context** is part of the authentication; wrong or missing context → `InvalidCiphertextException` on decrypt.
- **Client-side encryption**: you encrypt before sending to AWS (**AWS Encryption SDK**, DynamoDB Encryption Client / DynamoDB item encryption, S3 Encryption Client). AWS never sees plaintext. **Server-side encryption (SSE)**: the service encrypts for you with your KMS key.
- **Client-side vs server-side**: client-side gives maximum control and protects against service-side exposure but needs key handling and breaks server-side features (querying, indexing, Athena on encrypted columns).
- **S3 envelope**: S3 SSE-KMS uses `GenerateDataKey` per object (or per bucket with Bucket Keys).

## B. Request quotas and throttling
- KMS has a **shared request quota per account per Region** for cryptographic operations (`Encrypt`, `Decrypt`, `GenerateDataKey`, etc.). Default is **thousands per second** (for example 5,500, 10,000 or 30,000 for symmetric keys depending on the Region) and **lower for asymmetric** and for custom key stores **(verify exact numbers)**.
- Quotas apply across **all** keys in the account/Region (one noisy workload can throttle the rest).
- Over quota → `ThrottlingException` (HTTP 400). SDKs retry with backoff.
- **Mitigations**: S3 **Bucket Keys**, **data key caching**, **fewer encrypt calls** (batch), request an **increase**, spread across Regions, use **multi-Region keys** per Region, avoid `GenerateDataKey` per tiny record.
- **Control-plane** APIs (CreateKey, PutKeyPolicy…) have separate lower limits.
- KMS is **highly available** (multi-AZ in a Region); if a Region is down, keys are unavailable unless you use **multi-Region keys** in another Region.

## C. Rotation
- **AWS managed keys**: rotated **every year automatically**; cannot change.
- **Customer managed keys**: rotation is **optional**.
  - **Automatic rotation** works for **symmetric encryption keys with AWS_KMS origin**. Default period **365 days**; configurable **90 to 2,560 days** via `RotationPeriodInDays` **(verify bounds)**. Restrict with `kms:RotationPeriodInDays`.
  - **On-demand rotation**: for symmetric keys with AWS_KMS **or EXTERNAL** origin; **max 25 times per key** (hard limit); does not change the automatic schedule.
  - **Manual rotation** (create a new key and repoint an **alias**): for **asymmetric, HMAC, custom key store** keys, or when you want a new key ID.
- **What rotation does**: creates **new key material**; the **key ID/ARN/policies stay the same**. KMS keeps **all older material** to decrypt old ciphertext. New encrypts use the **current** material.
- **What it does NOT do**: does not re-encrypt existing data, does not rotate **data keys**, does not protect against a compromised data key.
- **Imported key material**: no automatic rotation; on-demand is possible after you import new material (multi-Region: import into all replicas first).
- **Disabled keys / pending deletion**: rotation paused; catch-up rotation happens on re-enable if overdue.
- **Cost**: first and second rotation add $1/month each.
- **Monitoring**: CloudTrail `RotateKey` events, EventBridge `KMS CMK Rotation`, `GetKeyRotationStatus`, `ListKeyRotations`.
- **Manual rotation downside**: apps that hard-code key IDs must switch; use **aliases** in apps (`alias/app-data`) so you repoint instead of redeploy. Old ciphertext still needs the **old key** (keep it enabled).
- **Compliance**: annual rotation is the common requirement (CIS 3.x/Security Hub control "KMS key rotation enabled").

## D. Multi-Region keys
- **Multi-Region keys (MRKs)** are **related keys in different Regions with the same key ID prefix (`mrk-…`) and same key material**, so ciphertext from one Region can be decrypted in another **without re-encrypting or cross-Region calls**.
- Components: **primary key** and **replica keys**. Each is an independent KMS key with its own **key policy, grants, aliases, state, and billing** ($1 each).
- **Shared properties** synced from primary: key material, key spec/usage/origin, rotation settings. **Not shared**: key policy, aliases, grants, tags, enabled state.
- Use cases: **global DynamoDB tables** (encrypted with MRKs), **cross-Region S3 replication / backups / DR**, **Aurora Global Database**, **active-active apps**, **client-side encryption** moving data across Regions.
- **Primary promotion**: update primary to a replica for failover (`UpdatePrimaryRegion`).
- **Caveat**: AWS services usually **do not auto-replicate encrypted data** with MRKs; they still do their own cross-Region copy (re-encrypting for S3 replication with the destination key).
- **Not the same as** replicating one key by copying: no way to export key material.
- Deleting: all replicas must be removed before the primary can be deleted.
- Use **MRKs only when you need** interoperability across Regions; otherwise use separate single-Region keys per Region (simpler data residency).

## E. Custom key stores
- **AWS CloudHSM key store**: key material generated and stored in **your CloudHSM cluster** (single tenant). Requires ≥2 HSMs in 2 AZs for availability. KMS key limited to **symmetric AES-256** (and some asymmetric) **(verify)**. You pay HSM hourly. Quotas: **10 custom key stores** per account/Region.
- **External key store (XKS)**: key material in an **external key manager** (on-prem HSM or third party) via an **XKS proxy**. Every crypto call goes out; latency higher; if the proxy is down, data is **unavailable**. Use for **sovereignty** needs.
- Custom key store KMS keys: **no automatic/on-demand rotation**; some features limited (multi-Region keys, grants for some services).
- **Key state `Unavailable`** when the key store is disconnected.
- Most workloads should use the **standard KMS key store**.

## F. Importing key material (BYOK)
- Steps: create KMS key (origin EXTERNAL) → `GetParametersForImport` (public wrapping key + import token) → wrap your key with the public key (RSA-OAEP/RSAES; AES for some) → `ImportKeyMaterial` with optional **expiry**.
- Parameters expire (token ~**24 hours**).
- You must keep **your own copy** of the material; if lost after deletion, data may be unrecoverable.
- You can **re-import the same material** to restore a deleted/expired key.
- **No automatic rotation**; **expiration** automatically makes the key unusable.
- Use only when policy requires your own key origin; otherwise AWS_KMS origin is simpler and safer.

## G. Asymmetric and HMAC keys (quick)
- **Asymmetric**: public key can be shared outside AWS (verify signatures offline); private key never leaves KMS. Requests cost more and have lower quotas. Services like **Private CA, IoT, CloudFront signed URL** (via other mechanisms) use signing keys.
- **RSA encrypt limits**: max plaintext depends on key size and padding (for example RSA-2048 OAEP-SHA256 ≈ 190 bytes).
- **HMAC keys**: `GenerateMac`/`VerifyMac`; the key never leaves KMS; useful for **tokenization, webhook signatures, deterministic IDs**.
- **Data masking tie-in**: use **HMAC** to create consistent pseudonyms (same input → same token) without storing the raw value; use **Macie/Glue** for discovery and masking transforms.

## H. Encryption at rest vs in transit (context)
- KMS handles **at rest** (and envelope keys). **In transit** uses TLS (ACM certificates, service TLS). Enforce TLS with `aws:SecureTransport` in bucket policies.
- **Hybrid post-quantum TLS** is supported on some AWS endpoints **(verify)**.
- **EBS/RDS/Redshift/S3**: encryption setting is often **fixed at creation** (EBS volumes can be re-encrypted by snapshot copy; RDS encrypted by snapshot copy; Redshift by modifying cluster; S3 objects by copy/batch operations).

## I. Monitoring KMS
- **CloudTrail** logs every KMS API call, including `Decrypt` by service principals (with encryption context so you can see which resource used the key). **Key policy changes** (`PutKeyPolicy`), `ScheduleKeyDeletion`, `DisableKey`, `CreateGrant`, `RetireGrant`.
- **CloudWatch metrics** (`AWS/KMS`): `SecondsUntilKeyMaterialExpiration` (imported keys), custom key store metrics; plus **CloudTrail-based metric filters** for deletion/disable events.
- **EventBridge** events: `KMS CMK Rotation`, `KMS Imported Key Material Expiration`, `KMS CMK Deletion`.
- **AWS Config rules**: `cmk-backing-key-rotation-enabled`, `kms-cmk-not-scheduled-for-deletion`, `encrypted-volumes`, `s3-bucket-server-side-encryption-enabled`, `rds-storage-encrypted`, `redshift-cluster-kms-enabled`.
- **Security Hub** controls for KMS: key rotation enabled, keys not pending deletion, policies not public.
- **Access Analyzer** flags KMS keys shared externally.
- **GuardDuty** can detect suspicious KMS use patterns (for example disabling/deleting keys) **(verify)**.

## J. Exam skills mapping
- **4.3.2 Encryption keys (KMS)**: envelope encryption, rotation.
- **4.3.3 Encryption across account boundaries**: multi-Region and cross-Region.
- **4.3.4 Encryption in transit or before transit**: encryption before transit (client-side).
- **4.3.1 Masking and anonymization**: HMAC tokens for pseudonymization.

## K. Scenarios: "If X → Y, because Z"
- If you must encrypt a 5 GB file with KMS → **`GenerateDataKey` + local AES encryption (envelope)**, because direct `Encrypt` is limited to 4,096 bytes.
- If you want to change which key protects stored data without exposing plaintext → **`ReEncrypt`**, because it decrypts and encrypts inside KMS.
- If compliance wants yearly key rotation without app changes → **enable automatic rotation on the symmetric CMK**, because the key ID stays the same and old data still decrypts.
- If a symmetric key was rotated and old objects still decrypt → **expected**, because KMS keeps all older key material versions.
- If you need to rotate an asymmetric signing key → **create a new key and repoint the alias; keep the old for verify**, because asymmetric keys cannot rotate automatically.
- If an encrypted DynamoDB global table spans Regions → **multi-Region key (primary + replicas)**, because each replica Region can decrypt without cross-Region KMS calls.
- If a Region fails and you need to decrypt there → **MRK replica in another Region**, because single-Region keys depend on their Region.
- If KMS calls from S3 SSE-KMS are throttled and expensive → **enable S3 Bucket Keys**, because they cut KMS requests by up to ~99% **(verify)**.
- If an app hits `ThrottlingException` across services → **reduce calls, cache data keys, request a quota increase**, because the cryptographic request quota is shared per account per Region.
- If a regulator demands that key material never leaves your datacenter → **XKS external key store**, because KMS only proxies operations.
- If apps break after you rotated by creating a new key → **use aliases in code**, because aliases can repoint without redeploying.
- If you need consistent but irreversible tokens for PII → **HMAC KMS key (`GenerateMac`)**, because the same input yields the same MAC without storing the plaintext.

Verified from AWS docs on 2026-11-03 (KMS key rotation, resource quotas, pricing, key policies).
Unconfirmed (verify): per-Region cryptographic request quota values; automatic rotation period bounds (90–2,560); S3 Bucket Keys savings percent; RSA plaintext limits; HSM key store key-spec support; hybrid post-quantum TLS endpoint coverage; GuardDuty KMS findings; EventBridge event names for KMS.
