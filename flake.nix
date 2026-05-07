{
  description = "JARVIS OS — Personal AI-Native Operating System";

  inputs = {
    nixpkgs.url         = "github:NixOS/nixpkgs/nixos-unstable";
    home-manager        = { url = "github:nix-community/home-manager"; inputs.nixpkgs.follows = "nixpkgs"; };
    hyprland            = { url = "github:hyprwm/Hyprland";            inputs.nixpkgs.follows = "nixpkgs"; };
  };

  outputs = { self, nixpkgs, home-manager, hyprland, ... }@inputs:
    let
      system = "x86_64-linux";
    in {
      nixosConfigurations.jarvis = nixpkgs.lib.nixosSystem {
        inherit system;
        specialArgs = { inherit inputs; };
        modules = [
          ./hardware-configuration.nix
          ./configuration.nix
          home-manager.nixosModules.home-manager
          {
            home-manager = {
              useGlobalPkgs      = true;
              useUserPackages    = true;
              extraSpecialArgs   = { inherit inputs; };
              users.sas          = import ./home.nix;
            };
          }
          hyprland.nixosModules.default
          ./modules/jarvis.nix
          ./modules/audio.nix
        ];
      };
    };
}
