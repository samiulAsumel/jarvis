{ pkgs, ... }:

{
  # ── Pipewire (modern audio stack) ─────────────────────────────────────────
  services.pipewire = {
    enable            = true;
    alsa.enable       = true;
    alsa.support32Bit = true;
    pulse.enable      = true;
    jack.enable       = true;

    extraConfig.pipewire."92-low-latency" = {
      context.properties = {
        default.clock.rate          = 48000;
        default.clock.quantum       = 512;   # lower = less latency for voice
        default.clock.min-quantum   = 32;
        default.clock.max-quantum   = 8192;
      };
    };
  };

  hardware.pulseaudio.enable = false; # disabled — pipewire handles pulse compat

  # ── Voice pipeline packages ────────────────────────────────────────────────
  environment.systemPackages = with pkgs; [
    # STT: whisper.cpp — fast local speech-to-text
    # Build from source with CUDA if available; CPU build works fine for base.en
    (pkgs.callPackage ../pkgs/whisper-cpp.nix {} or pkgs.whisper-cpp or pkgs.writeShellScriptBin "whisper-cpp" ''
      echo "whisper-cpp not found — install manually or add overlay" >&2
      exit 1
    '')
    # TTS: piper — neural, offline, low-latency
    (pkgs.piper-tts or pkgs.writeShellScriptBin "piper" ''
      echo "piper-tts not found — install manually or add overlay" >&2
      exit 1
    '')
    # Audio utilities for the voice pipeline
    sox
    alsa-utils
    pulseaudio # pactl CLI (works with pipewire-pulse)
  ];

  # Allow real-time audio for the voice pipeline
  security.pam.loginLimits = [
    { domain = "@audio"; type = "-"; item = "rtprio";  value = "95"; }
    { domain = "@audio"; type = "-"; item = "memlock"; value = "unlimited"; }
  ];
  users.groups.audio = {};
}
