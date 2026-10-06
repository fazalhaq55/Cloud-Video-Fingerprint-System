---

**File: `Decoder_App/README.md`**
```markdown
# Dashcam Decoder (Insurance Side)

## Project Overview
This web application is used by insurance administrators to retrieve and cryptographically verify the integrity of dashcam footage submitted for claims. 

## Technical Choices
* **Frontend:** HTML5, CSS3, and JavaScript, designed with a modern SaaS architecture for administrative ease of use.
* **Backend API:** FastAPI (Python) for secure communication with the database.
* **Database:** Supabase (PostgreSQL) serves as the immutable ledger for our data.

## Integrity Verification Mechanism
The core of this system relies on cryptographic immutability:
1. When a driver submits a raw video, the frames are hashed using the SHA-256 algorithm.
2. The Decoder application queries the Supabase cloud ledger for the specific `driver_id`.
3. It compares the sequence of hashes from the submitted video against the exact sequence of hashes recorded in the cloud during the drive.
4. Because SHA-256 is highly sensitive to changes (the avalanche effect), if a single pixel in the submitted video was altered using editing software, the hash will change entirely, and the Decoder will flag the frame as tampered/corrupted.

## Data Retention Management
To comply with privacy standards, the system features an administrative cleanup protocol. By triggering the `/api/cleanup` endpoint, the system automatically purges all cryptographic records older than 2 hours from the PostgreSQL database.

## Installation & Execution
1. Install Python 3.
2. Install the required dependencies: `pip install fastapi uvicorn supabase python-dotenv pydantic`
3. Create a `.env` file in the root directory with your Supabase credentials:
   ```env
   SUPABASE_URL=your_url
   SUPABASE_KEY=your_key