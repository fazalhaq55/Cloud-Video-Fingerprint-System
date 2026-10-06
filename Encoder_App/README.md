# Dashcam Encoder (Driver Side)

## Project Overview
This mobile web application simulates a dashcam mounted on a vehicle's windshield. It continuously acquires live video frames, generates cryptographic hashes in real-time, and transmits them to a secure cloud ledger.

## Technical Choices
* **Frontend:** HTML5, CSS3, and native JavaScript. 
* **Frame Acquisition:** Uses the HTML5 `<video>` and `<canvas>` API to capture live image data directly from the device's camera without heavy external libraries.
* **Hashing:** Utilizes the browser's native `crypto.subtle` Web Crypto API to generate secure SHA-256 hashes client-side. This prevents sending heavy video files over the network.
* **Backend API:** FastAPI (Python) was chosen for its speed and asynchronous capabilities to handle high-frequency data transmission.
* **Database:** Supabase (PostgreSQL) acts as the cloud ledger.

## Network Interruption Handling
To handle offline states (e.g., driving through a tunnel), the application implements a local caching mechanism:
1. If the `fetch` request to the cloud fails, the hash payload is appended to an array stored in the browser's `localStorage`.
2. A background synchronization loop runs every 3 seconds.
3. Once the network is restored, the loop detects the queued items and sequentially transmits them to the cloud, ensuring zero data loss.

## Installation & Execution
1. Install Python 3.
2. Install the required dependencies: `pip install fastapi uvicorn supabase python-dotenv pydantic`
3. Create a `.env` file in the root directory with your Supabase credentials:
   ```env
   SUPABASE_URL=your_url
   SUPABASE_KEY=your_key