# jarvis-os/core/executor.py
import subprocess
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("JarvisExecutor")


class JarvisExecutor:
    def __init__(self, dry_run=False):
        self.dry_run = dry_run
        self.forbidden_commands = ["rm -rf /", "mkfs", "dd if="]

    def execute(self, command):
        logger.info(f"Executing command: {command}")

        # Basic safety check
        for forbidden in self.forbidden_commands:
            if forbidden in command:
                return f"Blocked: Command '{command}' is too dangerous to execute automatically."

        if self.dry_run:
            return f"[Dry Run] Would have executed: {command}"

        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                return (
                    result.stdout if result.stdout else "Command executed successfully."
                )
            else:
                return f"Error: {result.stderr}"
        except subprocess.TimeoutExpired:
            return "Error: Command timed out."
        except Exception as e:
            return f"Unexpected error: {str(e)}"
