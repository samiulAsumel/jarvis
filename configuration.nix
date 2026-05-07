{ config, pkgs, inputs, lib, ... }:

{
  # ── Boot ──────────────────────────────────────────────────────────────────
  boot.loader = {
    systemd-boot.enable      = true;
    efi.canTouchEfiVariables = true;
  };

  # ── Networking ────────────────────────────────────────────────────────────
  networking = {
    hostName           = "jarvis";
    networkmanager.enable = true;
    firewall = {
      enable           = true;
      allowedTCPPorts  = [ 11434 8787 ]; # Ollama, JARVIS daemon
    };
  };

  # ── Locale / Time ─────────────────────────────────────────────────────────
  time.timeZone      = "Asia/Kolkata"; # <CHANGE_ME>
  i18n.defaultLocale = "en_US.UTF-8";

  # ── Users ─────────────────────────────────────────────────────────────────
  users.users.sas = {
    isNormalUser = true;
    extraGroups  = [ "wheel" "audio" "video" "networkmanager" "docker" "input" ];
    shell        = pkgs.bash;
  };
  security.sudo.wheelNeedsPassword = false;

  # ── Display / Hyprland ────────────────────────────────────────────────────
  programs.hyprland = {
    enable          = true;
    xwayland.enable = true;
  };

  services.greetd = {
    enable = true;
    settings.default_session = {
      command = "${pkgs.greetd.tuigreet}/bin/tuigreet --time --cmd Hyprland";
      user    = "greeter";
    };
  };

  xdg.portal = {
    enable       = true;
    extraPortals = [ pkgs.xdg-desktop-portal-hyprland ];
  };

  # ── Ollama (Local LLM) ────────────────────────────────────────────────────
  services.ollama = {
    enable        = true;
    # acceleration = "cuda";  # uncomment for NVIDIA; "rocm" for AMD
    listenAddress = "127.0.0.1:11434";
  };

  # ── NVIDIA (uncomment if applicable) ──────────────────────────────────────
  # hardware.nvidia = {
  #   modesetting.enable = true;
  #   open               = false;
  #   nvidiaSettings     = true;
  #   package            = config.boot.kernelPackages.nvidiaPackages.stable;
  # };
  # services.xserver.videoDrivers = [ "nvidia" ];

  # ── Fonts ─────────────────────────────────────────────────────────────────
  fonts.packages = with pkgs; [
    nerd-fonts.jetbrains-mono
    nerd-fonts.fira-code
    inter
    source-serif-pro
  ];

  # ── System Packages ───────────────────────────────────────────────────────
  environment.systemPackages = with pkgs; [
    # CLI essentials
    git curl wget jq ripgrep fd bat eza fzf tmux btop
    # Wayland stack
    wezterm rofi-wayland waybar swww hyprpaper
    grim slurp wl-clipboard
    # Audio tools
    pavucontrol helvum
    # Dev runtimes
    python312 uv nodejs_22 bun rustup
    # Containers / IaC
    docker docker-compose
    # Media
    mpv ffmpeg
    # AI
    ollama
    # Nix utilities
    nix-tree nix-diff
  ];

  # ── Security ──────────────────────────────────────────────────────────────
  security.polkit.enable = true;
  security.rtkit.enable  = true;

  # ── Docker ────────────────────────────────────────────────────────────────
  virtualisation.docker = {
    enable         = true;
    autoPrune.enable = true;
  };

  # ── Nix ───────────────────────────────────────────────────────────────────
  nix = {
    settings = {
      experimental-features = [ "nix-command" "flakes" ];
      auto-optimise-store   = true;
      trusted-users         = [ "root" "sas" ];
      substituters          = [ "https://hyprland.cachix.org" "https://cache.nixos.org/" ];
      trusted-public-keys   = [ "hyprland.cachix.org-1:a7pgxzMz7+chwVL3/pzj6jIBMioiJM7ypFP8PwtkuGc=" "cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY=" ];
    };
    gc = {
      automatic = true;
      dates     = "weekly";
      options   = "--delete-older-than 14d";
    };
  };

  nixpkgs.config.allowUnfree = true;
  system.stateVersion         = "24.11";
}
