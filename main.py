# jarvis-os/main.py
from core.brain import JarvisBrain
from core.executor import JarvisExecutor
import sys


def main():
    print("Jarvis OS Initialized. Hello, sir.")

    # In a real scenario, these would be loaded from config/settings.yaml
    brain = JarvisBrain(provider="ollama", model="llama3")
    executor = JarvisExecutor(dry_run=False)

    while True:
        try:
            user_input = input("\nJarvis > ")
            if user_input.lower() in ["exit", "quit", "shutdown"]:
                print("Shutting down. Goodbye, sir.")
                break

            # 1. Ask the brain what to do
            system_prompt = (
                "You are Jarvis, an AI OS. If the user asks you to do something that requires a system command, "
                "respond ONLY with 'CMD: <command>' followed by the command. "
                "If it is a general question, respond normally."
            )
            response = brain.query(user_input, system_prompt=system_prompt)

            # 2. Check if brain wants to execute a command
            if response.startswith("CMD: "):
                command = response[5:].strip()
                print(f"Executing: {command}...")
                result = executor.execute(command)

                # 3. Feed result back to brain for a natural response
                final_prompt = f"User asked: {user_input}\nYou executed: {command}\nResult: {result}\nPlease explain the result to the user concisely."
                final_response = brain.query(final_prompt)
                print(f"Jarvis: {final_response}")
            else:
                print(f"Jarvis: {response}")

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"System Error: {e}")


if __name__ == "__main__":
    main()
