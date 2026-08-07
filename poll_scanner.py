import subprocess
import sys
import time

from scan_lock import ScanLock


def run_scan():
    return subprocess.run(
        [sys.executable, "analysis/scan_smc.py"], capture_output=True, text=True
    )


def main():
    print("Memulai pemindaian otomatis... (Mengecek setiap 60 detik)")
    print("Tekan Ctrl+C untuk berhenti.")
    sys.stdout.flush()

    while True:
        with ScanLock() as lock:
            if not lock.acquired:
                print("aegis_bot.py sedang berjalan — scanner dilewati.")
                time.sleep(60)
                continue
            try:
                result = run_scan()
                if result.returncode != 0:
                    print(f"Scan gagal (exit {result.returncode}):\n{result.stderr}")
                elif "NO TRADE" not in result.stdout:
                    print("\nSETUP VALID DITEMUKAN!\n")
                    print(result.stdout)
                    sys.stdout.flush()
                # Keep looping — a single catch shouldn't stop the scanner.
                # db.log_signal() already dedups by setup identity, so a setup
                # that's still valid next pass won't re-queue.
                time.sleep(60)
            except Exception as e:
                print(f"Error: {e}")
                time.sleep(60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nScanner dihentikan.")