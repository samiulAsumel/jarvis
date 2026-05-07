{ config, pkgs, lib, ... }:

let
  cfg = config.services.jarvis;

  # Python env with all daemon dependencies
  jarvisPython = pkgs.python312.withPackages (ps: with ps; [
    fastapi uvicorn httpx aiofiles pydantic pydantic-settings
    anthropic ollama-python
    chromadb
    psutil
    rich typer
    numpy sounddevice
    # sqlite3 is stdlib
  ]);

  jarvisPackage = pkgs.stdenv.mkDerivation {
    pname   = "jarvis";
    version = "0.1.0";
    src     = ../daemon;
    installPhase = ''
      mkdir -p $out/lib/jarvis $out/bin
      cp -r src/jarvis $out/lib/
      cat > $out/bin/jarvis <<'EOF'
      #!/bin/sh
      exec ${jarvisPython}/bin/python -m jarvis.cli "$@"
      EOF
      chmod +x $out/bin/jarvis
    '';
  };

in {
  options.services.jarvis = {
    enable       = lib.mkEnableOption "JARVIS AI daemon";
    user         = lib.mkOption { type = lib.types.str; default = "sas"; };
    port         = lib.mkOption { type = lib.types.port; default = 8787; };
    ollamaModel  = lib.mkOption { type = lib.types.str; default = "llama3.3:70b"; };
    fastModel    = lib.mkOption { type = lib.types.str; default = "qwen2.5:7b"; };
    configDir    = lib.mkOption { type = lib.types.path; default = "/home/sas/.config/jarvis"; };
  };

  config = lib.mkIf cfg.enable {
    # Ensure Ollama is up before JARVIS starts
    services.ollama.enable = true;

    # JARVIS main API daemon
    systemd.services.jarvis-daemon = {
      description   = "JARVIS AI Daemon";
      wantedBy      = [ "multi-user.target" ];
      after         = [ "network.target" "ollama.service" ];
      requires      = [ "ollama.service" ];

      environment = {
        JARVIS_PORT          = toString cfg.port;
        JARVIS_OLLAMA_MODEL  = cfg.ollamaModel;
        JARVIS_FAST_MODEL    = cfg.fastModel;
        JARVIS_CONFIG_DIR    = cfg.configDir;
        PYTHONPATH           = "${jarvisPython}/${jarvisPython.sitePackages}";
      };

      serviceConfig = {
        Type             = "exec";
        User             = cfg.user;
        WorkingDirectory = cfg.configDir;
        ExecStart        = "${jarvisPython}/bin/python -m jarvis.main";
        Restart          = "on-failure";
        RestartSec       = "5s";

        # Hardening — daemon only needs home dir + /etc/nixos for self-update
        ProtectSystem        = "strict";
        ReadWritePaths       = [ "/home/${cfg.user}" "/etc/nixos" ];
        PrivateTmp           = true;
        NoNewPrivileges      = true;
        ProtectKernelModules = true;
        ProtectKernelTunables = true;
        ProtectControlGroups = true;

        # Logging
        StandardOutput = "journal";
        StandardError  = "journal";
        SyslogIdentifier = "jarvis";
      };
    };

    # JARVIS voice listener (wake word + STT/TTS) — user-space
    systemd.user.services.jarvis-voice = {
      description = "JARVIS Voice Pipeline";
      after       = [ "jarvis-daemon.service" "pipewire.service" ];
      wantedBy    = [ "graphical-session.target" ];

      environment = {
        JARVIS_HOST = "http://127.0.0.1:${toString cfg.port}";
        PYTHONPATH  = "${jarvisPython}/${jarvisPython.sitePackages}";
      };

      serviceConfig = {
        ExecStart    = "${jarvisPython}/bin/python -m jarvis.voice.wake";
        Restart      = "on-failure";
        RestartSec   = "3s";
      };
    };

    # Pull default Ollama models on first boot
    systemd.services.jarvis-model-pull = {
      description   = "Pull JARVIS Ollama models";
      wantedBy      = [ "multi-user.target" ];
      after         = [ "ollama.service" ];
      requires      = [ "ollama.service" ];
      serviceConfig = {
        Type      = "oneshot";
        User      = cfg.user;
        ExecStart = pkgs.writeShellScript "pull-models" ''
          ${pkgs.ollama}/bin/ollama pull ${cfg.fastModel}
          ${pkgs.ollama}/bin/ollama pull ${cfg.ollamaModel}
        '';
        RemainAfterExit = true;
      };
    };

    # Expose `jarvis` CLI for the user
    environment.systemPackages = [ jarvisPackage ];

    # Config directory + key file template on first activation
    system.activationScripts.jarvisConfig = ''
      install -d -m 700 -o ${cfg.user} ${cfg.configDir}
      install -d -m 700 -o ${cfg.user} /home/${cfg.user}/.local/share/jarvis/{memory,chroma}
      if [ ! -f ${cfg.configDir}/anthropic_key ]; then
        echo "" > ${cfg.configDir}/anthropic_key
        chmod 600 ${cfg.configDir}/anthropic_key
        chown ${cfg.user} ${cfg.configDir}/anthropic_key
      fi
    '';
  };
}
