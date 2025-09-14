import json
import shlex
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

from flask import Flask, jsonify, request


app = Flask(__name__)


DEFAULT_BEMCLI_MODULE_PATH = r"C:\\Program Files\\Veritas\\Backup Exec\\Modules\\PowerShell3\\BEMCLI"


def _escape_for_single_quoted_powershell(value: str) -> str:
    """Escape a Python string for safe insertion into a single-quoted PowerShell string.

    PowerShell single-quoted strings escape a single quote by doubling it.
    """
    return value.replace("'", "''")


def _build_powershell_script(
    path: str,
    agent_server: Optional[str] = None,
    module_path: Optional[str] = None,
    recurse: bool = False,
    path_is_directory: bool = False,
) -> str:
    """Build the PowerShell script to import BEMCLI and run a catalog search with diagnostics.

    Returns a string that is executed with `powershell.exe -NoProfile -ExecutionPolicy Bypass -Command <script>`.
    """

    ps_module_path = module_path or DEFAULT_BEMCLI_MODULE_PATH

    ps_escaped_path = _escape_for_single_quoted_powershell(path)
    ps_escaped_agent = _escape_for_single_quoted_powershell(agent_server) if agent_server else ""
    ps_escaped_module = _escape_for_single_quoted_powershell(ps_module_path) if ps_module_path else ""

    # Compose the PowerShell logic with diagnostics and multiple attempts/patterns.
    lines: List[str] = [
        "$ErrorActionPreference = 'Stop'",
        "$ProgressPreference = 'SilentlyContinue'",
        f"$modulePath = '{ps_escaped_module}'",
        "# Diagnostics container",
        "$diag = [ordered]@{}",
        "$diag.PSVersion = $PSVersionTable.PSVersion.ToString()",
        "$diag.PSEdition = $PSVersionTable.PSEdition",
        "$diag.MachineName = $env:COMPUTERNAME",
        "# Import BEMCLI",
        "$diag.moduleImport = [ordered]@{ tried=$modulePath }",
        "try {",
        "  if ($modulePath -and (Test-Path $modulePath)) {",
        "    Import-Module $modulePath -Force",
        "  } else {",
        "    Import-Module BEMCLI -Force",
        "  }",
        "  $mod = Get-Module BEMCLI",
        "  $diag.moduleImport.success = $true",
        "  $diag.moduleImport.loadedPath = $mod.Path",
        "  $diag.moduleImport.version = $mod.Version.ToString()",
        "} catch {",
        "  $diag.moduleImport.success = $false",
        "  $diag.moduleImport.error = $_.Exception.Message",
        "}",
        f"$queryPath = '{ps_escaped_path}'",
        f"$agentName = '{ps_escaped_agent}'",
        "$diag.queryPath = $queryPath",
        "$diag.agentRequested = $agentName",
        "$diag.identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name",
        "$diag.hasSearchBECatalog = [bool](Get-Command Search-BECatalog -ErrorAction SilentlyContinue)",
        f"$recurse = ${str(recurse).lower()}",
        f"$pathIsDir = ${str(path_is_directory).lower()}",
        "$diag.recurse = $recurse",
        "$diag.pathIsDirectory = $pathIsDir",
        "# Determine patterns to try",
        "$pathsToTry = @()",
        "$pathsToTry += $queryPath",
        "if (-not ($queryPath -match '[*?]') -and $queryPath -ne '') {",
        "  $pathsToTry += ($queryPath + '*')",
        "  $pathsToTry += ('*' + $queryPath + '*')",
        "}",
        "if ($queryPath -eq '') { $pathsToTry = @('*') }",
        "# Also try drive-less and basename patterns (e.g., 'D:\\toBackup' -> 'toBackup*')",
        "$drvLess = $queryPath -replace '^[A-Za-z]:\\',''",
        "if ($drvLess -and $drvLess -ne $queryPath) {",
        "  $pathsToTry += $drvLess",
        "  if (-not ($drvLess -match '[*?]')) { $pathsToTry += ($drvLess + '*') }",
        "}",
        "# UNC form: \\server\\share\\folder -> share\\folder",
        "if ($queryPath.StartsWith('\\\\')) {",
        "  $uncLess = $queryPath -replace '^\\\\[^\\]+\\',''",
        "  if ($uncLess) {",
        "    $pathsToTry += $uncLess",
        "    if (-not ($uncLess -match '[*?]')) { $pathsToTry += ($uncLess + '*') }",
        "  }",
        "}",
        "$leaf = Split-Path $queryPath -Leaf",
        "if ($leaf -and -not ($leaf -match '[*?]')) { $pathsToTry += ($leaf + '*') }",
        "$pathsToTry = $pathsToTry | Where-Object { $_ -and $_.Trim() -ne '' } | Select-Object -Unique",
        "$diag.pathsToTry = $pathsToTry",
        "# Collect available agents (names only)",
        "try { $diag.agentsAvailable = (Get-BEAgentServer | Select-Object -ExpandProperty Name) } catch { $diag.agentsAvailable = @(); }",
        "# Basic environment validation",
        "try { $diag.backupSetCount = (Get-BEBackupSet | Measure-Object).Count } catch { $diag.backupSetCount = $null }",
        "try { $diag.sampleJob = (Get-BEJob | Select-Object -First 1 -ExpandProperty Name) } catch { $diag.sampleJob = $null }",
        "$resultsAll = @()",
        "$attempts = @()",
        "function Invoke-BECatalogSearch([string]$p, $server = $null, [bool]$dir=$pathIsDir) {",
        "  if ($server) {",
        "    if ($recurse -and $dir) { return $server | Search-BECatalog -Path $p -Recurse -PathIsDirectory }",
        "    elseif ($recurse) { return $server | Search-BECatalog -Path $p -Recurse }",
        "    elseif ($dir) { return $server | Search-BECatalog -Path $p -PathIsDirectory }",
        "    else { return $server | Search-BECatalog -Path $p }",
        "  } else {",
        "    if ($recurse -and $dir) { return Search-BECatalog -Path $p -Recurse -PathIsDirectory }",
        "    elseif ($recurse) { return Search-BECatalog -Path $p -Recurse }",
        "    elseif ($dir) { return Search-BECatalog -Path $p -PathIsDirectory }",
        "    else { return Search-BECatalog -Path $p }",
        "  }",
        "}",
        "function Add-Attempt([string]$name, [string]$pattern, [scriptblock]$block) {",
        "  $a = [ordered]@{ name=$name; pattern=$pattern; success=$true; count=0 }",
        "  try {",
        "    $r = & $block",
        "    if ($r) { $arr = @($r); $resultsAll += $arr; $a.count = $arr.Count }",
        "  } catch {",
        "    $a.success = $false; $a.error = $_.Exception.Message",
        "  }",
        "  $attempts += [pscustomobject]$a",
        "}",
        "$dirToggles = @($pathIsDir); if (-not $pathIsDir) { $dirToggles += $true }",
        "foreach ($p in $pathsToTry) {",
        "  foreach ($dir in $dirToggles) {",
        "  if ($diag.moduleImport.success -and $agentName) {",
        "    $server = $null",
        "    try { $server = Get-BEAgentServer -Name $agentName } catch {}",
        "    if ($server) { Add-Attempt ("agent_pipe_dir=" + $dir) $p { Invoke-BECatalogSearch -p $p -server $server -dir $dir } }",
        "    else { $attempts += [pscustomobject]@{ name='agent_lookup'; pattern=$p; success=$false; error='Agent not found' } }",
        "  }",
        "  Add-Attempt ("direct_dir=" + $dir) $p { Invoke-BECatalogSearch -p $p -dir $dir }",
        "  Add-Attempt ("all_agents_dir=" + $dir) $p { Get-BEAgentServer | ForEach-Object { Invoke-BECatalogSearch -p $p -server $_ -dir $dir } }",
        "  }",
        "}",
        "$diag.attempts = $attempts",
        "[pscustomobject]@{ diagnostics = $diag; results = @($resultsAll) } | ConvertTo-Json -Depth 6",
    ]

    return "; ".join(lines)


def _run_powershell(script: str, timeout_seconds: int = 120) -> Tuple[int, str, str, str]:
    """Run the provided PowerShell script and return (code, stdout, stderr, used_binary)."""
    # Prefer powershell.exe on Windows. If only PowerShell 7 is available (pwsh),
    # the caller may adjust this binary; we try powershell first.
    used_binary = "powershell.exe"
    cmd = [
        used_binary,
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        script,
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return proc.returncode, proc.stdout, proc.stderr, used_binary
    except FileNotFoundError:
        # Fallback to pwsh if powershell.exe is not present (e.g., PowerShell 7 only)
        used_binary = "pwsh"
        cmd[0] = used_binary
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return proc.returncode, proc.stdout, proc.stderr, used_binary


def search_catalog(
    path: str,
    agent_server: Optional[str] = None,
    module_path: Optional[str] = None,
    recurse: bool = False,
    path_is_directory: bool = False,
) -> Dict[str, Any]:
    """Search the Backup Exec catalog for a given path using BEMCLI.

    Returns a dict with keys: success (bool), results (list), error (str|None).
    """
    ps_script = _build_powershell_script(
        path=path,
        agent_server=agent_server,
        module_path=module_path,
        recurse=recurse,
        path_is_directory=path_is_directory,
    )
    code, out, err, used_bin = _run_powershell(ps_script)

    if code != 0:
        return {
            "success": False,
            "results": [],
            "error": err.strip() or f"PowerShell exited with code {code}",
            "diagnostics": {
                "ps": {"binary": used_bin, "exit_code": code, "stderr": err, "script": ps_script},
                "raw_stdout": out,
            },
        }

    stdout = out.strip()
    if not stdout:
        # No output translates to empty result set
        return {"success": True, "results": [], "error": None}

    # PowerShell ConvertTo-Json may emit non-JSON preamble in rare cases; attempt to parse robustly.
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        # Try to locate the first JSON array/object in the output
        first_bracket = min((i for i in [stdout.find("["), stdout.find("{")] if i != -1), default=-1)
        if first_bracket != -1:
            try:
                parsed = json.loads(stdout[first_bracket:])
            except json.JSONDecodeError:
                return {
                    "success": False,
                    "results": [],
                    "error": "Failed to parse JSON from PowerShell output.",
                    "diagnostics": {
                        "ps": {"binary": used_bin, "exit_code": code, "stderr": err, "script": ps_script},
                        "raw_stdout": out,
                    },
                }
        else:
            return {
                "success": False,
                "results": [],
                "error": "No JSON output from PowerShell.",
                "diagnostics": {
                    "ps": {"binary": used_bin, "exit_code": code, "stderr": err, "script": ps_script},
                    "raw_stdout": out,
                },
            }
    # Expecting an object with keys 'results' and 'diagnostics'
    diagnostics: Dict[str, Any] = {}
    results_payload: Any = parsed
    if isinstance(parsed, dict) and "results" in parsed:
        results_payload = parsed.get("results")
        diagnostics = parsed.get("diagnostics") or {}

    # Normalize to list
    results_list: List[Dict[str, Any]]
    if isinstance(results_payload, list):
        results_list = results_payload
    elif results_payload is None:
        results_list = []
    else:
        results_list = [results_payload]

    # Attach ps exec diagnostics too
    diagnostics = diagnostics or {}
    diagnostics["ps"] = {"binary": used_bin, "exit_code": code}

    return {"success": True, "results": results_list, "error": None, "diagnostics": diagnostics}


@app.get("/search")
def http_search() -> Any:
    """HTTP endpoint to search the Backup Exec catalog.

    Query params:
      - path (required): The path or wildcard pattern to search (e.g., C:\\Data\\Projects\\*).
      - agent (optional): Name of the Agent Server to scope the search.
      - modulepath (optional): Full path to the BEMCLI module folder.
    """
    query_path = request.args.get("path", type=str)
    if not query_path:
        return jsonify({"error": "Missing required query parameter 'path'"}), 400

    agent = request.args.get("agent", type=str)
    module_path = request.args.get("modulepath", type=str)
    recurse = request.args.get("recurse", default="false", type=str).lower() in ("1", "true", "yes", "on")
    path_is_dir = request.args.get("isdir", default="false", type=str).lower() in ("1", "true", "yes", "on")

    result = search_catalog(
        path=query_path,
        agent_server=agent,
        module_path=module_path,
        recurse=recurse,
        path_is_directory=path_is_dir,
    )
    status_code = 200 if result.get("success") else 500
    payload = {
        "success": result["success"],
        "count": len(result.get("results", [])),
        "results": result.get("results", []),
        "error": result.get("error"),
        "diagnostics": result.get("diagnostics"),
    }
    return jsonify(payload), status_code


@app.get("/health")
def http_health() -> Any:
    return jsonify({"status": "ok"})


 # Root route removed (no HTML UI)


if __name__ == "__main__":
    # Example: python backup_exec_api.py --path "C:\\Data\\*"
    if len(sys.argv) > 1 and sys.argv[1] == "--path" and len(sys.argv) > 2:
        path_arg = sys.argv[2]
        agent_arg = None
        module_arg = None
        # Optional flags
        for i, token in enumerate(sys.argv):
            if token == "--agent" and i + 1 < len(sys.argv):
                agent_arg = sys.argv[i + 1]
            if token == "--modulepath" and i + 1 < len(sys.argv):
                module_arg = sys.argv[i + 1]
        res = search_catalog(path=path_arg, agent_server=agent_arg, module_path=module_arg)
        print(json.dumps(res, indent=2))
    else:
        app.run(host="0.0.0.0", port=5000)


