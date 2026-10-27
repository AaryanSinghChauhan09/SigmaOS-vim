    # SigmaOS-vim

    Editor config (xed + lazyvim)

    Part of the **SigmaOS** sovereign operating-system ecosystem — a multi-repository
    distribution modelled on Linux Mint and Omarchy Linux. See the parent
    [`SigmaOS`](https://github.com/AaryanSinghChauhan09/SigmaOS) repository for the
    full component index.

    ## Upstream inspirations
    - https://github.com/linuxmint/xed
- https://github.com/omacom/omarchy-lazyvim

    ## Design principles applied
    - **Separation of Concerns**
- **Defensive Programming**
- **Fail-Fast**
- **DRY**
- **KISS**
- **Deterministic Testing**

    ## Usage
    Verbs: `plugins, health, install-plan, config-gen`

    ```
    $ sigma-nvim plugins --manifest plugins.json
folke/lazy.nvim        dir=lazy/folke--lazy.nvim     ref=main
$ sigma-nvim install-plan --manifest plugins.json --packpath ~/.local/share/nvim/lazy
$ sigma-nvim health --manifest plugins.json --facts facts.json
$ sigma-nvim config-gen --manifest plugins.json --distro aether.nvim

    ```

    ## Build & test
    ```
    make build
    make test
    ```

    ## Licence
    GNU General Public License v3.0 (FOSS).
