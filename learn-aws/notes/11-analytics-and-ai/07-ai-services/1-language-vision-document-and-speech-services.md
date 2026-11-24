# AWS AI services – 1. Language, document, vision and speech services

Short notes. Each point is a fact you can be asked about. These are **pre-trained, API-first** services: no ML infrastructure to run. Compare with Bedrock (foundation models) and SageMaker AI (your own models).

## A. How to choose (the quick rule)
- **Standard task, no training data, want it cheap and fast** → an **AI service** (Textract, Comprehend, Rekognition, Transcribe, Translate, Polly, Lex).
- **Flexible reasoning, summarizing, extraction with changing schemas** → **Bedrock** (or Bedrock Data Automation for documents/media).
- **Your own algorithm/data/GPU control** → **SageMaker AI**.
- **Pay model**: per **request/page/image/minute/character/unit**; **no servers**; **custom models** (Comprehend custom, Rekognition Custom Labels) add **training and endpoint/inference-hour charges**.
- **Pipeline pattern**: S3 event → **Lambda/Step Functions** → AI service (sync for small, **async + SNS** for large) → results to **S3/DynamoDB/OpenSearch** → Athena/QuickSight/Bedrock.
- **Lifecycle watch (AWS docs, 2026)**: several AI services or features are in **maintenance mode** (table in file 3). Check status before a new build.

## B. Amazon Textract (documents → text and structure)
- **What**: ML **OCR plus structure**. Reads **printed and handwritten** text, **forms (key-value pairs)**, **tables**, **queries** (ask a question, get the answer), **signatures**, **layout**.
- **APIs**:
  - `DetectDocumentText`: lines and words only.
  - `AnalyzeDocument` with **feature types**: **TABLES, FORMS, QUERIES, SIGNATURES, LAYOUT** (priced per feature per page).
  - **`AnalyzeExpense`**: invoices and receipts (vendor, totals, line items).
  - **`AnalyzeID`**: identity documents (US government IDs and passports per docs; other regions vary **(verify)**).
  - **Analyze Lending**: mortgage packages: classify and route pages to the right analysis, with summaries.
  - **Custom Queries**: adapt Queries to your documents by training an **adapter**.
- **Sync vs async**:
  - **Synchronous**: **single-page** images/PDF, low latency. Size limit about **10 MB** **(verify)**.
  - **Asynchronous** (`Start*` then `Get*`): **multi-page PDF/TIFF** (up to about **3,000 pages / 500 MB**) **(verify)**; completion via **SNS**; input must be in **S3**.
- **Output**: JSON **blocks** (PAGE, LINE, WORD, TABLE, CELL, KEY_VALUE_SET, QUERY...) with **geometry** and **confidence**; convert to CSV/text with the **textract-response-parser** or **trp** library.
- **Quality control**: **Augmented AI (A2I)** human review for low confidence (**A2I is in maintenance for new customers: verify**), or your own review UI/threshold.
- **Pricing**: **per page**, tiered; **feature types add cost** (tables, forms, queries each priced).
- **Security**: IAM, **KMS**, VPC endpoint (PrivateLink), CloudTrail; document data handling per service terms (AI service opt-out policy through **AWS Organizations AI services opt-out policy**).
- **Use with Bedrock**: Textract extracts text/tables → Bedrock summarizes/classifies; or use **Bedrock Data Automation** for flexible schemas (see Bedrock notes).
- **Choose**: Textract for **cheap, high-volume, structured extraction** with stable formats; BDA/LLM for **varied layouts and semantic fields**.

## C. Amazon Comprehend (text NLP)
- **What**: **NLP insights** from text with **pre-trained models**: **entities**, **key phrases**, **sentiment** and **targeted sentiment**, **language**, **syntax (part of speech)**, **PII detection and redaction**, **events**, **topic modeling** (clustering), **toxicity/prompt safety classification**.
- **Custom** (AutoML, no coding): **custom classification** (multi-class, multi-label) and **custom entity recognition**. Input can be **text, PDF, Word, images** for custom models. **Flywheels** automate retraining and evaluation of custom models.
- **Modes**: **real-time (synchronous)** for small text, **asynchronous jobs** on **S3** corpora (with **KMS** for volume and output), **batch** APIs.
- **Custom models need an endpoint** for real-time inference (**billed per inference unit while it exists**; delete when unused).
- **Pricing**: per **unit of 100 characters** (min 3 units per request), custom model **training per hour**, **model storage/management**, **endpoint hours**; flywheel itself free but iterations cost training/storage.
- **Status**: the whole service is active, but **Topic Modeling, Event Detection and Prompt Safety Classification** are in **maintenance** (announced 31 Mar 2026). Use **Bedrock/LLMs and Guardrails** for those needs.
- **PII**: `DetectPiiEntities` / `ContainsPiiEntities` / **redaction jobs** to mask or replace; pair with **Macie** (S3 sensitive data discovery) and **Lake Formation**.
- **Comprehend content may be stored to improve pre-trained models** unless you **opt out** (AI services opt-out policy).
- **Comprehend Medical**: separate service for **clinical text** (medical entities, PHI detection, **ICD-10-CM, RxNorm, SNOMED CT ontology linking**). **HIPAA-eligible** **(verify current status)**.
- **Choose**: Comprehend for **cheap high-volume sentiment/entities/PII**; LLM for **summaries, nuanced classification, free-form extraction**.

## D. Amazon Rekognition (images and video)
- **Image analysis**: **object/scene/label detection**, **text in images**, **face detection/analysis (attributes)**, **face comparison**, **face search** in **collections** (index faces first, then search), **celebrity recognition**, **content moderation** (unsafe content), **PPE detection**, **image properties** (quality, color, sharpness).
- **Video analysis** (stored videos in S3): **labels, faces, celebrities, text, moderation, segment detection** (black frames, credits, shots). **Async**: `Start*` → **SNS** → `Get*`. **Streaming video** via **Kinesis Video Streams** + **stream processors** (face search).
- **Face Liveness**: confirms a **live person** (anti-spoofing: photos, videos, masks, injected deepfakes) for identity verification.
- **Custom Labels**: train **custom classifiers/detectors** from your labeled images (logos, products). **Model must be started (billed per inference-hour) and stopped**.
- **Adapters** improve content moderation / label detection for your image domain.
- **Status**: **Streaming Events** and **Batch Image Content Moderation** are in **maintenance** (announced 31 Mar 2026). The core image/video APIs remain.
- **Pricing**: per image/per minute of video; face storage per month for collections; Custom Labels per inference hour + training hour.
- **Privacy**: **responsible use** policies for face features; **opt-out policy** for content use; store face vectors, not images, in collections; control access with IAM.
- **Pipeline**: S3 upload → Lambda → Rekognition → results in DynamoDB/OpenSearch for **searchable media libraries**.

## E. Amazon Transcribe (speech → text)
- **Batch** (audio/video in **S3**) and **streaming** (HTTP/2 or **WebSocket**) transcription; **automatic language identification**, **multi-language**, **custom vocabularies** and **custom language models**, **vocabulary filtering**, **speaker diarization**, **channel identification**, **PII redaction**, **toxicity detection**, **timestamps and confidence**, **subtitle files** (SRT/VTT).
- **Call Analytics**: **sentiment, talk speed, interruptions, non-talk time, issue/outcome/category rules**, **generative call summarization** (uses Bedrock) **(verify)**.
- **Transcribe Medical** (clinical dictation/conversations) — **HIPAA-eligible** **(verify status)**.
- **Output**: JSON to S3 (encrypted with KMS); drive downstream **Comprehend/Bedrock** analysis, OpenSearch indexing.
- **Pricing**: **per second of audio** (batch/streaming, 15 s minimum per request), add-ons billed extra (call analytics, redaction).
- **Choose**: Transcribe for **call-center and media transcription**; Bedrock multimodal models can transcribe too but cost more per minute **(verify)**.

## F. Amazon Translate
- **Neural machine translation** between many languages; **real-time** (`TranslateText`, up to about **10,000 bytes** per request) **(verify)** and **batch** (`StartTextTranslationJob` over S3 files/documents) and **document translation** (txt, html, docx, pptx, xlsx, xliff).
- **Customization**: **custom terminology** (glossary of terms to force), **Active Custom Translation** (parallel data), **formality** and **profanity masking**, **brevity**.
- **Auto language detection** (`auto` source).
- **Pricing**: **per character**.
- **Pattern**: Transcribe → Translate → Polly for **speech-to-speech**; Translate before **Comprehend** for multilingual analytics.

## G. Amazon Polly (text → speech)
- **Voices**: **Standard, Neural, Long-form, Generative** engines; many languages and voices; **SSML** (speed, pitch, pauses, pronunciation), **lexicons** (custom pronunciation), **speech marks** (word timings and visemes for lip-sync), **Brand Voice** (custom, via AWS engagement).
- **Modes**: `SynthesizeSpeech` (short text to stream), **async tasks** (long text to S3 with SNS).
- **Pricing**: **per character** (neural/generative cost more than standard).
- **Use**: IVR, accessibility, e-learning, voice assistants.

## H. Amazon Lex (conversational bots)
- **Build voice and text chatbots** with **intents**, **slots** (parameters), **utterances**, **fulfillment (Lambda)**, **sessions and context**, **versions/aliases**, **multi-language**, **built-in intents** (like Kendra search/QnA intent), **generative AI features** (assisted slot resolution, QnA with Bedrock, descriptive bot builder) **(verify)**.
- **Integrations**: **Amazon Connect** contact flows, **Lambda**, **Kendra/Bedrock KB** for FAQ, **CloudWatch/Conversation logs (S3/CloudWatch)**, messaging channels (Slack, Facebook, Twilio via integrations).
- **Pricing**: **per text/speech request**; streaming per 15 s of audio.
- **Choose**: Lex for **structured task bots** (book, check status) with predictable flows; **Bedrock agents/AgentCore** for **open-ended agentic** behavior.

## I. Security, governance and cost (all AI services)
- **IAM** per API (for example `textract:AnalyzeDocument`, `rekognition:DetectLabels`, `comprehend:DetectPiiEntities`, `transcribe:StartTranscriptionJob`); **data access roles** (service assumes your role to read S3 and write output).
- **Encryption**: **KMS** for output/volume (async jobs), **TLS** in transit, **VPC endpoints (PrivateLink)** for private access.
- **Data use opt-out**: **AWS Organizations AI services opt-out policy** stops AWS using your content to improve services (applies to many AI services).
- **Logging**: **CloudTrail** for API calls, **CloudWatch** metrics (requests, errors, throttles), **EventBridge/SNS** for async job completion.
- **Throttling**: each API has **TPS quotas** (adjustable); use **retries with backoff**, **async APIs**, SQS buffering.
- **Cost control**: filter documents (avoid re-processing), choose **cheapest feature set** (for example `DetectDocumentText` vs `AnalyzeDocument` with tables), **batch/async**, delete **custom model endpoints**, tier discounts at volume, **cache results** (S3/DynamoDB), **Budgets/Anomaly Detection**.
- **Accuracy**: always use **confidence thresholds**, **human review** for important decisions, **evaluate on your data**, and consider bias in face/language models.

## J. Scenarios: "If X → Y, because Z"
- If 5 million scanned invoices must become vendor/total/line-item data → **Textract `AnalyzeExpense` (async) → S3/DynamoDB**, because it is built for invoices with structured output.
- If forms of varying layouts need semantic fields → **Bedrock Data Automation or LLM extraction** (Textract for OCR first), because schemas and layouts vary.
- If you need PII masked in text logs → **Comprehend PII redaction** (plus Macie for S3 discovery), because it detects and redacts entities.
- If customer reviews need sentiment per product → **Comprehend sentiment/targeted sentiment (or an LLM)**, because they output positive/negative/mixed per entity cheaply.
- If a media library must be searchable by objects and faces → **Rekognition labels + face collections into OpenSearch**, because it indexes visual content and faces.
- If users must prove they are live during onboarding → **Rekognition Face Liveness**, because it detects spoofing and deepfake injection.
- If call-center audio needs transcripts plus sentiment and compliance flags → **Transcribe Call Analytics (then Bedrock summaries)**, because it adds diarization and analytics rules.
- If a website must support 10 languages with fixed brand terms → **Translate with custom terminology**, because it forces your glossary.
- If an IVR needs natural voices → **Polly neural/generative voices with SSML**, because they sound natural and are tunable.
- If you need a bot that books appointments with defined slots → **Lex with Lambda fulfillment**, because intents and slots structure the dialog.
- If you need topic modeling or event detection from Comprehend → **migrate to LLM-based clustering/extraction**, because those Comprehend features are in maintenance.
- If a Custom Labels or Comprehend custom endpoint keeps billing → **stop/delete the model/endpoint**, because they bill while running.

Verified from AWS docs on 2026-11-01 (Textract, Comprehend and Rekognition overview pages; lifecycle summary for Comprehend/Rekognition feature statuses and dates).
Unconfirmed (verify): Textract size/page limits and `AnalyzeID` document coverage; Comprehend limits and unit minimums; Transcribe Call Analytics generative summaries and minimum billing seconds; Translate request size limits and Active Custom Translation details; Polly engine names; Lex generative features; HIPAA eligibility of Medical variants; whether A2I availability affects Textract review flows.
