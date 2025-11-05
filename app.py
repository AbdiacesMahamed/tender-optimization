
"""Desktop launcher for the Tender Optimization Streamlit app.

Starts a headless Streamlit server and opens a native window using pywebview.

Usage (dev):
	python app.py

When packaging, use the provided `build_windows.ps1` script which installs
the desktop requirements and runs PyInstaller.
"""

import sys
import os
import subprocess
import time
import signal
import webbrowser
from pathlib import Path

try:
	import requests
except Exception:
	pass

# pywebview is optional and disabled by default because it can initialize CLR
# on Windows and crash in environments without WebView2. To enable native
# mode set the environment variable USE_PYWEBVIEW=1 or pass --native on the
# command line.
USE_PYWEBVIEW = ("USE_PYWEBVIEW" in os.environ and os.environ["USE_PYWEBVIEW"] == "1") or ("--native" in sys.argv)
webview = None
if USE_PYWEBVIEW:
	try:
		import webview  # type: ignore
	except Exception:
		webview = None

HERE = Path(__file__).parent.resolve()
DASHBOARD = HERE / "dashboard.py"
PORT = 8501
URL = f"http://127.0.0.1:{PORT}"


def start_streamlit():
	"""Start Streamlit as a subprocess using the same Python executable.

	Returns the subprocess.Popen instance.
	"""
	cmd = [
		sys.executable,
		"-m",
		"streamlit",
		"run",
		str(DASHBOARD),
		"--server.port",
		str(PORT),
		"--server.headless",
		"true",
		"--server.runOnSave",
		"false",
	]
	# Start streamlit and keep its output visible for debugging
	return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def wait_for_server(url, timeout=60):
	start = time.time()
	while time.time() - start < timeout:
		try:
			r = requests.get(url, timeout=1)
			if r.status_code == 200:
				return True
		except Exception:
			pass
		time.sleep(0.5)
	return False


def main():
	if not DASHBOARD.exists():
		print(f"Could not find {DASHBOARD}. Run this from the project root.")
		raise SystemExit(1)

	print("Starting Streamlit server...")
	proc = start_streamlit()

	try:
		print(f"Waiting for Streamlit at {URL} ...")
		if not wait_for_server(URL, timeout=60):
			print("Streamlit failed to start in time. See logs.")
			# show subprocess stderr for debugging
			if proc.stderr:
				err = proc.stderr.read().decode(errors='ignore')
				print(err)
			proc.kill()
			raise SystemExit(1)

		print("Opening system browser...")
		if webview is not None:
			try:
				print("Attempting native window via pywebview...")
				webview.create_window("Tender Optimization", URL, width=1200, height=800)
				webview.start()
			except Exception as e:
				print("pywebview failed, opening system browser instead:", e)
				webbrowser.open(URL)
				try:
					input("Press Enter to stop the server and exit...\n")
				except Exception:
					pass
		else:
			webbrowser.open(URL)
			try:
				input("Press Enter to stop the server and exit...\n")
			except Exception:
				pass

	finally:
		try:
			print("Stopping Streamlit server...")
			# Try graceful termination
			proc.terminate()
			proc.wait(timeout=5)
		except Exception:
			try:
				proc.kill()
			except Exception:
				pass


if __name__ == "__main__":
	main()
