"""Image-owned isolated-interpreter entrypoint for the fixed scheduler."""
import sys
sys.path.insert(0, "/usr/lib/haos")
from haos.backup_schedule import main
main()
