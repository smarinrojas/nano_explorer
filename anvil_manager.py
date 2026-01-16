import subprocess
import time
import os
import signal
import threading
from collections import deque

class AnvilManager:
    def __init__(self, port=8545):
        self.process = None
        self.port = port
        self.current_config = {}
        self.lock = threading.Lock()
        self.logs = deque(maxlen=2000) # Store last 2000 lines
        self.stop_logging = threading.Event()

    def _log_reader(self, proc):
        """Reads stdout from the process and appends to logs."""
        try:
            for line in iter(proc.stdout.readline, b''):
                if self.stop_logging.is_set():
                    break
                try:
                    decoded_line = line.decode('utf-8', errors='replace').rstrip()
                    if decoded_line:
                        with self.lock:
                            self.logs.append(decoded_line)
                except Exception:
                    pass
        except ValueError:
            pass # Handle closed file
        finally:
            if proc.stdout:
                proc.stdout.close()

    def is_running(self):
        with self.lock:
            return self.process is not None and self.process.poll() is None

    def _kill_process_on_port(self):
        """Finds and kills any process listening on the configured port."""
        try:
            # lsof -t -i:PORT returns the PID of the process
            pid_str = subprocess.check_output(["lsof", "-t", "-i", f":{self.port}"]).decode().strip()
            if pid_str:
                pids = pid_str.split('\n')
                for pid in pids:
                    if pid:
                        print(f"Force killing process {pid} on port {self.port}")
                        os.kill(int(pid), signal.SIGKILL)
                time.sleep(1) # Give OS a moment to release the port
        except (subprocess.CalledProcessError, ValueError, OSError):
            pass # No process found or error killing it

    def start_fork(self, fork_url, chain_id=None):
        self.stop() # Stop any existing instance managed by this class
        self._kill_process_on_port() # Ensure port is free regardless of who owns it

        cmd = ["anvil", "--port", str(self.port), "--fork-url", fork_url]
        if chain_id:
            cmd.extend(["--chain-id", str(chain_id)])
        
        cmd.extend(["--host", "0.0.0.0"])

        print(f"Starting Anvil: {' '.join(cmd)}")
        
        with self.lock:
            try:
                # Merge stderr into stdout to capture everything in one stream
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    preexec_fn=os.setsid
                )
                
                self.logs.clear()
                self.stop_logging.clear()
                
                # Start logging thread
                t = threading.Thread(target=self._log_reader, args=(self.process,))
                t.daemon = True
                t.start()

                self.current_config = {
                    'fork_url': fork_url,
                    'chain_id': chain_id,
                    'port': self.port,
                    'start_time': time.time()
                }
                return True, "Anvil started successfully"
            except FileNotFoundError:
                return False, "Anvil executable not found. Please install Foundry."
            except Exception as e:
                return False, str(e)

    def stop(self):
        with self.lock:
            if self.process:
                self.stop_logging.set()
                try:
                    os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                    self.process.wait(timeout=5)
                except Exception:
                    try:
                        os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                    except:
                        pass
                finally:
                    self.process = None
                    self.current_config = {}
                return True
            return False

    def get_status(self):
        running = self.is_running()
        return {
            'running': running,
            'pid': self.process.pid if running and self.process else None,
            'config': self.current_config if running else {}
        }
    
    def get_logs(self):
        with self.lock:
            return list(self.logs)

# Global instance
anvil_manager = AnvilManager()
