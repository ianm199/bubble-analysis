import * as vscode from "vscode";
import {
  LanguageClient,
  LanguageClientOptions,
  ServerOptions,
  TransportKind,
} from "vscode-languageclient/node";

let client: LanguageClient | undefined;

export function activate(context: vscode.ExtensionContext) {
  const config = vscode.workspace.getConfiguration("flow");
  const pythonPath = config.get<string>("pythonPath") || "python3";

  const serverOptions: ServerOptions = {
    command: pythonPath,
    args: ["-m", "bubble.lsp"],
    transport: TransportKind.stdio,
  };

  const clientOptions: LanguageClientOptions = {
    documentSelector: [{ scheme: "file", language: "python" }],
  };

  client = new LanguageClient(
    "bubble-lsp",
    "Flow Exception Analysis",
    serverOptions,
    clientOptions
  );

  client.start();
}

export function deactivate(): Thenable<void> | undefined {
  return client?.stop();
}
