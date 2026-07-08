/* Native launcher for LocalFlow.app.
 *
 * The bundle's main executable must be a real binary: script executables run
 * under /bin/sh, so TCC attributes permission checks to Apple's sh instead of
 * the app — Accessibility grants to "LocalFlow" then never match. This stub
 * fork/execs the venv console script; the child inherits the app's
 * responsible-process attribution, so grants land on LocalFlow.app.
 */
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

static pid_t child = 0;

static void forward_signal(int sig) {
    if (child > 0) kill(child, SIGTERM);
}

int main(int argc, char **argv) {
    const char *home = getenv("HOME");
    if (home == NULL) return 1;

    char script[1024];
    snprintf(script, sizeof script, "%s/.localflow/venv/bin/localflow", home);

    /* Finder launches get a minimal PATH; parakeet needs Homebrew's ffmpeg. */
    const char *old_path = getenv("PATH");
    char path[4096];
    snprintf(path, sizeof path, "/opt/homebrew/bin:/usr/local/bin:%s",
             old_path ? old_path : "/usr/bin:/bin:/usr/sbin:/sbin");
    setenv("PATH", path, 1);

    signal(SIGTERM, forward_signal);
    signal(SIGINT, forward_signal);

    child = fork();
    if (child == 0) {
        argv[0] = script;
        execv(script, argv);
        perror("localflow launcher: execv");
        _exit(127);
    }
    if (child < 0) return 1;

    int status = 0;
    while (waitpid(child, &status, 0) < 0) {
        /* interrupted by our signal handler; keep waiting for the child */
    }
    return WIFEXITED(status) ? WEXITSTATUS(status) : 128;
}
