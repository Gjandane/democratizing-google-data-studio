/** Where the agent setup scripts live (conventions 1.7, Build agent). */
const SETUP_BASE = 'https://raw.githubusercontent.com/Gjandane/democratizing-google-data-studio/main/agent-setup';

export interface SetupCommands {
  powershell: string;
  bash: string;
}

/**
 * The setup commands of conventions 1.7 ("Setup command"): `job` runs a build's one-shot job,
 * `check` runs the setup check. `origin` is this app's origin, `code` the ticket or check code.
 */
export function setupCommands(origin: string, flag: 'job' | 'check', code: string): SetupCommands {
  const ps = flag === 'job' ? '-Job' : '-Check';
  return {
    powershell: `& ([scriptblock]::Create((irm ${SETUP_BASE}/setup.ps1))) -Server ${origin} ${ps} ${code}`,
    bash: `curl -fsSL ${SETUP_BASE}/setup.sh | bash -s -- --server ${origin} --${flag} ${code}`,
  };
}
