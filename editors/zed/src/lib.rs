use zed_extension_api::{self as zed, settings::LspSettings, Result};

struct FlowExtension;

impl zed::Extension for FlowExtension {
    fn new() -> Self {
        Self
    }

    fn language_server_command(
        &mut self,
        _id: &zed::LanguageServerId,
        worktree: &zed::Worktree,
    ) -> Result<zed::Command> {
        if let Ok(lsp_settings) = LspSettings::for_worktree("bubble-lsp", worktree) {
            if let Some(binary) = lsp_settings.binary {
                if let Some(path) = binary.path {
                    let args = binary.arguments.unwrap_or_default();
                    return Ok(zed::Command {
                        command: path,
                        args,
                        env: worktree.shell_env(),
                    });
                }
            }
        }

        let python = worktree
            .which("python3")
            .or_else(|| worktree.which("python"))
            .ok_or_else(|| {
                "Python not found in PATH. Install bubble-analysis[lsp] and ensure python3 is available.".to_string()
            })?;

        Ok(zed::Command {
            command: python,
            args: vec!["-m".to_string(), "bubble.lsp".to_string()],
            env: worktree.shell_env(),
        })
    }

    fn language_server_initialization_options(
        &mut self,
        server_id: &zed::LanguageServerId,
        worktree: &zed::Worktree,
    ) -> Result<Option<zed::serde_json::Value>> {
        let settings = LspSettings::for_worktree(server_id.as_ref(), worktree)
            .ok()
            .and_then(|s| s.initialization_options.clone())
            .unwrap_or_default();
        Ok(Some(settings))
    }

    fn language_server_workspace_configuration(
        &mut self,
        server_id: &zed::LanguageServerId,
        worktree: &zed::Worktree,
    ) -> Result<Option<zed::serde_json::Value>> {
        let settings = LspSettings::for_worktree(server_id.as_ref(), worktree)
            .ok()
            .and_then(|s| s.settings.clone())
            .unwrap_or_default();
        Ok(Some(settings))
    }
}

zed::register_extension!(FlowExtension);
