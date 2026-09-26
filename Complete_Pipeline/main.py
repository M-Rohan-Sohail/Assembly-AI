import subprocess
import time
import sys
import signal
import os

def main():
    print("Starting ClearVoice 2.0 Complete Pipeline...")
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    ts_dir = os.path.join(base_dir, "ts_intelligence")
    python_dir = os.path.join(base_dir, "python_core")
    
    # 1. Start the Node.js Intelligence Server (Person 2)
    print("[1/3] Starting Person 2 Intelligence Server (Node.js)...")
    
    # Using npx ts-node to run server.ts
    node_process = subprocess.Popen(
        ["npx", "ts-node", "src/server.ts"],
        cwd=ts_dir,
        # Let it print to stdout/stderr
    )

    def cleanup(signum, frame):
        print("\nShutting down pipeline...")
        node_process.terminate()
        sys.exit(0)

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    # 2. Wait for Node.js server to be ready
    print("[2/3] Waiting for Node.js server to come online on port 8787...")
    time.sleep(5)
    
    if node_process.poll() is not None:
        print("Node.js server failed to start. Exiting.")
        sys.exit(1)
        
    print("Node.js server is ready.")

    # 3. Start Python STT & Orchestrator (Person 1 & 3)
    print("[3/3] Starting Python STT & Orchestrator Pipeline...")
    
    # Add python_core to PYTHONPATH so it resolves imports correctly
    env = os.environ.copy()
    env["PYTHONPATH"] = python_dir
    
    # Use the same python executable that ran this script
    python_process = subprocess.Popen(
        [sys.executable, "src/main.py"],
        cwd=python_dir,
        env=env
    )

    try:
        # Wait for Python to finish (or until user presses Ctrl+C)
        python_process.wait()
    except KeyboardInterrupt:
        print("\nInterrupted by user.")
    finally:
        # Cleanup
        print("Shutting down Node.js server...")
        node_process.terminate()
        node_process.wait()
        print("Pipeline shut down.")

if __name__ == "__main__":
    main()
