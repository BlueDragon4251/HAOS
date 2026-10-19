"""Fixed root-managed network rule for the external model-only CLI identity."""
import os
import pwd
import subprocess
from .network import NFT, rules, read_resolvers


def acp_rules(uid, resolvers):
    script = rules(uid, "haos_provider_acp", resolvers, provider=False)
    return "\n".join(line for line in script.splitlines()
                     if "ip daddr 127.0.0.1 tcp dport 9119 counter accept" not in line) + "\n"


def main():
    if os.geteuid() != 0:
        raise PermissionError("root-owned ACP network guard required")
    script = acp_rules(pwd.getpwnam("haos-provider-acp").pw_uid, read_resolvers())
    for args in ([NFT, "--check", "--file", "-"], [NFT, "--file", "-"]):
        subprocess.run(args, input=script, text=True, check=True, capture_output=True, timeout=20)


if __name__ == "__main__":
    main()
