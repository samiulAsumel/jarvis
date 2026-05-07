{ config, pkgs, lib, ... }:

{
  home.username      = "sas";
  home.homeDirectory = "/home/sas";
  home.stateVersion  = "24.11";

  # ── Shell ─────────────────────────────────────────────────────────────────
  programs.bash = {
    enable = true;
    bashrcExtra = ''
      # JARVIS CLI alias
      alias j='jarvis'
      alias jv='jarvis voice'
      alias js='jarvis status'

      # JARVIS env
      export JARVIS_HOST="http://127.0.0.1:8787"
      export ANTHROPIC_API_KEY="$(cat ~/.config/jarvis/anthropic_key 2>/dev/null || echo "")"

      # Quality-of-life
      eval "$(fzf --bash)"
    '';
  };

  # ── Hyprland ──────────────────────────────────────────────────────────────
  wayland.windowManager.hyprland = {
    enable = true;
    settings = {
      monitor         = ",preferred,auto,1";
      "$mod"          = "SUPER";
      "$terminal"     = "wezterm";
      "$menu"         = "rofi -show drun";

      general = {
        gaps_in   = 4;
        gaps_out  = 8;
        border_size = 2;
        "col.active_border"   = "rgba(00d4ffff) rgba(0066ffff) 45deg";
        "col.inactive_border" = "rgba(1a1a2ecc)";
      };

      decoration = {
        rounding     = 8;
        blur.enabled = true;
        blur.size    = 6;
        shadow.enabled = true;
      };

      animations = {
        enabled = true;
        bezier  = "smooth, 0.05, 0.9, 0.1, 1.05";
        animation = [
          "windows,     1, 5,  smooth, slide"
          "windowsOut,  1, 5,  smooth, slide"
          "fade,        1, 7,  default"
          "workspaces,  1, 6,  smooth, slide"
        ];
      };

      input = {
        kb_layout    = "us";
        follow_mouse = 1;
        touchpad.natural_scroll = true;
      };

      bind = [
        "$mod, Return, exec, $terminal"
        "$mod, Space,  exec, $menu"
        "$mod, Q,      killactive,"
        "$mod, F,      fullscreen,"
        "$mod, V,      togglefloating,"
        # JARVIS overlay — press Super+J to open AI chat
        "$mod, J, exec, jarvis overlay"
        # Workspaces
        "$mod, 1, workspace, 1"
        "$mod, 2, workspace, 2"
        "$mod, 3, workspace, 3"
        "$mod, 4, workspace, 4"
        "$mod, 5, workspace, 5"
        "$mod SHIFT, 1, movetoworkspace, 1"
        "$mod SHIFT, 2, movetoworkspace, 2"
        "$mod SHIFT, 3, movetoworkspace, 3"
        # Screenshot
        ", Print, exec, grim -g \"$(slurp)\" ~/Pictures/screenshot-$(date +%s).png"
      ];

      exec-once = [
        "waybar"
        "swww-daemon"
        "systemctl --user start jarvis-voice"  # wake word listener
      ];
    };
  };

  # ── Waybar ────────────────────────────────────────────────────────────────
  programs.waybar = {
    enable   = true;
    settings = [{
      layer    = "top";
      position = "top";
      modules-left   = [ "hyprland/workspaces" ];
      modules-center = [ "clock" ];
      modules-right  = [ "custom/jarvis" "cpu" "memory" "network" "pulseaudio" "battery" ];

      "custom/jarvis" = {
        exec     = "echo '🤖 JARVIS'";
        on-click = "jarvis overlay";
        format   = "{}";
      };
      clock        = { format = "{:%a %d %b  %H:%M}"; tooltip = false; };
      cpu          = { format = " {usage}%"; interval = 2; };
      memory       = { format = " {percentage}%"; interval = 2; };
      network      = { format-wifi = " {essid}"; format-ethernet = " {ifname}"; format-disconnected = "󰤭 offline"; };
      pulseaudio   = { format = "{icon} {volume}%"; format-icons = { default = [ "" "" "" ]; }; };
      battery      = { format = "{icon} {capacity}%"; format-icons = [ "" "" "" "" "" ]; };
    }];

    style = ''
      * { font-family: "JetBrainsMono Nerd Font"; font-size: 13px; }
      window#waybar { background: rgba(10, 10, 20, 0.85); color: #e0e0ff; border-bottom: 2px solid rgba(0, 212, 255, 0.4); }
      .modules-left, .modules-center, .modules-right { padding: 0 8px; }
      #custom-jarvis { color: #00d4ff; font-weight: bold; cursor: pointer; }
      #cpu { color: #ff6b6b; }
      #memory { color: #ffd93d; }
      #clock { color: #c3e6ff; }
      #battery.charging { color: #6bffb8; }
    '';
  };

  # ── WezTerm ───────────────────────────────────────────────────────────────
  programs.wezterm = {
    enable = true;
    extraConfig = ''
      local wezterm = require 'wezterm'
      return {
        font                 = wezterm.font("JetBrainsMono Nerd Font"),
        font_size            = 13.0,
        color_scheme         = "Catppuccin Mocha",
        window_background_opacity = 0.92,
        enable_tab_bar       = true,
        window_padding       = { left = 8, right = 8, top = 6, bottom = 6 },
        default_cursor_style = "BlinkingBar",
      }
    '';
  };

  # ── Git ───────────────────────────────────────────────────────────────────
  programs.git = {
    enable    = true;
    userName  = "sas";                         # <CHANGE_ME>
    userEmail = "sa.sumel91@gmail.com";
    extraConfig = {
      init.defaultBranch = "main";
      pull.rebase        = true;
    };
  };

  programs.home-manager.enable = true;
}
