"""Running a hill's evaluator inside its declared container image.

Used when a hill's manifest sets ``environment.image``. The tool never builds
images; it runs the evaluator inside a prebuilt one, using whatever runtime the
machine has. docker and podman take the same flags; apptainer and singularity
(its sibling — same CLI) run the OCI image via the ``docker://`` transport and
bind explicitly, converting the image on the fly.

Which runtime is used is auto-detected (docker, then podman, then apptainer /
singularity), but the caller decides the policy: pass ``--runtime`` on the CLI
or set ``HILLS_RUNTIME`` in the environment (the platform sets it per node) to
force one. The tool stays mechanism-only — it never guesses a runtime from the
hill, and never configures storage; that is the caller's job (e.g. point
podman's store at node-local disk via ``CONTAINERS_STORAGE_CONF`` when the home
is on NFS).

Paths are bound at their own absolute location (``host:host``, without resolving
symlinks) so the absolute paths the runner writes into invocation.json resolve
identically inside the container.

GPU passthrough for image hills is not wired yet; these run CPU-only for now.
"""

import os
import shutil
import subprocess
import uuid
from pathlib import Path

from hills import proc
from hills.errors import HillsError

# Order of auto-detect preference. podman is a drop-in for docker; apptainer and
# singularity are the HPC path (daemonless, run a docker:// image directly).
RUNTIMES = ("docker", "podman", "apptainer", "singularity")
# Daemonless runtimes: no background daemon, run an image as the current process,
# and share the same `exec --cleanenv --no-eval --pwd --bind --env` CLI.
_DAEMONLESS = ("apptainer", "singularity")
_READY_TIMEOUT_S = 20


def _usable(name: str) -> bool:
    """A runtime is usable only if it can actually run: for docker and podman
    that means the daemon or backend answers, not merely that the client exists.
    A daemonless runtime (apptainer/singularity) has no daemon, so presence is
    enough."""
    if name in _DAEMONLESS:
        return True
    try:
        result = subprocess.run(
            [name, "info"], capture_output=True, timeout=_READY_TIMEOUT_S
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def detect(preferred: str | None = None) -> str | None:
    """The runtime to use, or None if none is available.

    ``preferred`` (from ``--runtime`` or, if unset, the ``HILLS_RUNTIME`` env)
    forces a specific runtime: it is returned when it is on PATH and usable, and
    otherwise nothing else is substituted for it (an explicit choice that can't
    run is an error the caller should see, via :func:`require`). With no
    preference, the first usable runtime in :data:`RUNTIMES` wins.
    """
    preferred = preferred or os.environ.get("HILLS_RUNTIME") or None
    if preferred:
        if preferred not in RUNTIMES:
            return None
        return preferred if (shutil.which(preferred) and _usable(preferred)) else None
    for name in RUNTIMES:
        if shutil.which(name) and _usable(name):
            return name
    return None


def require(preferred: str | None = None) -> str:
    preferred = preferred or os.environ.get("HILLS_RUNTIME") or None
    runtime = detect(preferred)
    if runtime is not None:
        return runtime
    if preferred:
        if preferred not in RUNTIMES:
            raise HillsError(
                f"unknown container runtime {preferred!r}; choose one of "
                + ", ".join(RUNTIMES)
            )
        raise HillsError(
            f"the requested container runtime {preferred!r} is not on PATH or not usable."
        )
    raise HillsError(
        "this hill declares environment.image, which needs a working container runtime "
        "(docker, podman, apptainer, or singularity) on PATH; none was found or reachable."
    )


def _abs(path) -> str:
    # Absolute, but do NOT resolve symlinks: the mount destination must match the
    # spelling the runner uses in argv and invocation.json.
    return os.path.abspath(str(path))


def _bind_flags(runtime: str, binds: list[tuple[Path, bool]]) -> list[str]:
    flags: list[str] = []
    for host, read_only in binds:
        spec = _abs(host)
        if runtime in _DAEMONLESS:
            flags += ["--bind", f"{spec}:{spec}" + (":ro" if read_only else "")]
        else:
            flags += ["-v", f"{spec}:{spec}" + (":ro" if read_only else ":rw")]
    return flags


def _image_ref(runtime: str, image: str) -> str:
    if runtime not in _DAEMONLESS:
        return image
    # apptainer/singularity run an OCI image via the docker:// transport, or a
    # local .sif / explicit URI verbatim.
    if "://" in image or image.endswith(".sif"):
        return image
    return f"docker://{image}"


def build_command(
    runtime: str,
    image: str,
    argv: list[str],
    *,
    workdir: Path,
    binds: list[tuple[Path, bool]],
    env: dict | None = None,
) -> list[str]:
    """The full command line that runs ``argv`` inside ``image``.

    Only the given env vars are set; the image's own PATH and environment are
    kept, so a host PATH never shadows the image's interpreter. Any ENTRYPOINT
    the image declares is neutralized so ``argv`` runs as given.
    """
    env = env or {}
    workdir_s = _abs(workdir)
    if runtime in ("docker", "podman"):
        command = [runtime, "run", "--rm", "--init"]
        if runtime == "podman":
            # Rootless podman: map the invoking user to themselves so files on
            # bound mounts are owned correctly. (A no-op under rootful podman.)
            command += ["--userns=keep-id"]
        else:
            command += ["--user", f"{os.getuid()}:{os.getgid()}"]
        # Run argv exactly, regardless of the image's ENTRYPOINT.
        command += ["--entrypoint", argv[0]]
        command += ["-w", workdir_s]
        command += _bind_flags(runtime, binds)
        for key, value in env.items():
            command += ["-e", f"{key}={value}"]
        command += [image, *argv[1:]]
        return command
    # apptainer / singularity: a clean environment (no host PYTHON*), no host
    # env evaluation. The CLI name IS the runtime, so both work unchanged.
    command = [runtime, "exec", "--cleanenv", "--no-eval", "--pwd", workdir_s]
    command += _bind_flags(runtime, binds)
    for key, value in env.items():
        command += ["--env", f"{key}={value}"]
    command += [_image_ref(runtime, image), *argv]
    return command


def ensure_image(
    runtime: str, image: str, *, log_path: Path | None = None, stream: bool = False
) -> tuple[int, str]:
    """Make the image available before the timed run, so the watchdog does not
    count a first-time download or OCI-to-SIF conversion.

    Pulls only when the image is not already present, so a locally built image
    and offline cached digests both work. With ``stream=True`` the pull /
    OCI->SIF download progress is echoed live (to the run log a node captures),
    so a long first-time fetch is visible instead of a blank log.
    """
    if runtime in ("docker", "podman"):
        present = subprocess.run(
            [runtime, "image", "inspect", image], capture_output=True
        )
        if present.returncode == 0:
            return 0, ""
        return proc.stream_run([runtime, "pull", image], log_path=log_path, stream=stream)
    # apptainer / singularity: warm the OCI->SIF cache with a no-op exec (untimed).
    return proc.stream_run(
        [runtime, "exec", "--cleanenv", "--no-eval", _image_ref(runtime, image), "true"],
        log_path=log_path,
        stream=stream,
    )


def run(
    image: str,
    argv: list[str],
    *,
    workdir: Path,
    binds: list[tuple[Path, bool]],
    env: dict | None = None,
    timeout: float | None = None,
    log_path: Path | None = None,
    stream: bool = False,
    runtime: str | None = None,
) -> tuple[int, str]:
    """Run ``argv`` inside ``image``. Raises HillsError if no runtime is present.

    For docker and podman the container gets a name and is force-removed on
    timeout, since killing the client's process group does not stop a
    daemon-managed container. A daemonless runtime runs as the current process,
    so killing the process group is enough.
    """
    runtime = runtime or require()
    command = build_command(runtime, image, argv, workdir=workdir, binds=binds, env=env)
    name = None
    if runtime in ("docker", "podman"):
        name = f"hills-{uuid.uuid4().hex[:12]}"
        command = command[:2] + ["--name", name] + command[2:]
    try:
        return proc.stream_run(command, timeout=timeout, log_path=log_path, stream=stream)
    except BaseException:
        if name is not None:
            try:
                subprocess.run([runtime, "rm", "-f", name], capture_output=True, timeout=30)
            except (OSError, subprocess.TimeoutExpired):
                pass
        raise
