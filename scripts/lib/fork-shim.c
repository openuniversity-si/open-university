/* GATE-SPEED F4 (D-122): the client of scripts/lib/fork_server.py, installed as `python3` first on a script test's PATH.
 *
 * It hands the fork server its working directory and every open descriptor (SCM_RIGHTS; the server reads argv, the
 * environment, the umask, the signal state and the limits from /proc/<this pid>), then waits: the server answers
 * STARTED <pid> and later EXITED <wait status>, and this process exits the same way the fork did, forwarding the
 * signals it receives meanwhile. With no server, an unreachable one or a FALLBACK answer it execs the real interpreter
 * (OU_FORK_SERVER_PYTHON) with its own argv, so the caller sees `python3` either way. Built per run by
 * scripts/lib/gate_test_cache.py where a C compiler exists. */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <unistd.h>

#define MAX_FDS 250
#define REPLY_BYTES 5

static volatile pid_t child = 0;

/* The interpreter this python3 stands for: OU_FORK_SERVER_PYTHON, else the one the run built this client for (a
 * caller that built its own environment from nothing still runs the same interpreter). */
#ifndef REAL_PYTHON
#define REAL_PYTHON ""
#endif
static const char *real_python(void) {
  const char *named = getenv("OU_FORK_SERVER_PYTHON");
  if (named != NULL && *named != '\0') return named;
  return *REAL_PYTHON != '\0' ? REAL_PYTHON : NULL;
}

static void run_real(char **argv) {
  const char *real = real_python();
  if (real == NULL) {
    fprintf(stderr, "fork-shim: no python3 to run: OU_FORK_SERVER_PYTHON is not set\n");
    _exit(127);
  }
  argv[0] = (char *)real;
  execv(real, argv);
  fprintf(stderr, "fork-shim: cannot exec %s: %s\n", real, strerror(errno));
  _exit(127);
}

static void forward(int sig) {
  if (child > 0) kill(child, sig);
}

static int connect_server(void) {
  const char *folder = getenv("OU_FORK_SERVER");
  struct sockaddr_un address;
  if (folder == NULL || *folder == '\0') return -1;
  memset(&address, 0, sizeof address);
  address.sun_family = AF_UNIX;
  if (snprintf(address.sun_path, sizeof address.sun_path, "%s/socket", folder) >= (int)sizeof address.sun_path)
    return -1;
  int s = socket(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0);
  if (s < 0) return -1;
  if (connect(s, (struct sockaddr *)&address, sizeof address) != 0) {
    close(s);
    return -1;
  }
  return s;
}

/* Sends the working directory and the open descriptors; fills targets/count. 0 on success. */
static int send_request(int s, int *targets, int *count) {
  int fds[MAX_FDS + 1];
  int n = 0;
  int cwd = open(".", O_PATH | O_DIRECTORY | O_CLOEXEC);
  if (cwd < 0) return -1;
  fds[n++] = cwd;
  DIR *listing = opendir("/proc/self/fd");
  if (listing == NULL) return -1;
  int own = dirfd(listing);
  struct dirent *entry;
  *count = 0;
  while ((entry = readdir(listing)) != NULL) {
    if (entry->d_name[0] == '.') continue;
    int fd = atoi(entry->d_name);
    if (fd == own || fd == s || fd == cwd) continue;
    if (*count >= MAX_FDS) {
      closedir(listing);
      return -1;
    }
    targets[(*count)++] = fd;
    fds[n++] = fd;
  }
  closedir(listing);
  int32_t payload[MAX_FDS];
  for (int i = 0; i < *count; i++) payload[i] = targets[i];
  char control[CMSG_SPACE(sizeof(int) * (MAX_FDS + 1))];
  memset(control, 0, sizeof control);
  struct iovec io = {.iov_base = payload, .iov_len = sizeof(int32_t) * (*count)};
  char empty = 0;
  if (*count == 0) {
    io.iov_base = &empty;
    io.iov_len = 1;
  }
  struct msghdr message = {.msg_iov = &io, .msg_iovlen = 1, .msg_control = control,
                           .msg_controllen = CMSG_SPACE(sizeof(int) * n)};
  struct cmsghdr *header = CMSG_FIRSTHDR(&message);
  header->cmsg_level = SOL_SOCKET;
  header->cmsg_type = SCM_RIGHTS;
  header->cmsg_len = CMSG_LEN(sizeof(int) * n);
  memcpy(CMSG_DATA(header), fds, sizeof(int) * n);
  ssize_t sent = sendmsg(s, &message, MSG_NOSIGNAL);
  close(cwd);
  return sent < 0 ? -1 : 0;
}

static ssize_t reply(int s, char *buffer) {
  for (;;) {
    ssize_t got = recv(s, buffer, REPLY_BYTES, 0);
    if (got >= 0 || errno != EINTR) return got;
  }
}

int main(int argc, char **argv) {
  (void)argc;
  int targets[MAX_FDS];
  int count = 0;
  char buffer[REPLY_BYTES];
  int s = connect_server();
  if (s < 0) run_real(argv);
  if (send_request(s, targets, &count) != 0) {
    close(s);
    run_real(argv);
  }
  ssize_t got = reply(s, buffer);
  if (got != REPLY_BYTES || buffer[0] != 'P') {
    close(s);
    run_real(argv); /* FALLBACK, or a server that could not take it: nothing ran yet */
  }
  int32_t value;
  memcpy(&value, buffer + 1, sizeof value);
  child = value;
  /* The fork holds the descriptors now; this process keeps only stderr, for its own last words. */
  for (int i = 0; i < count; i++)
    if (targets[i] != 2) close(targets[i]);
  static const int signals[] = {SIGHUP, SIGINT, SIGQUIT, SIGTERM, SIGUSR1, SIGUSR2, SIGALRM, SIGWINCH, SIGCONT};
  for (size_t i = 0; i < sizeof signals / sizeof signals[0]; i++) {
    struct sigaction old;
    if (sigaction(signals[i], NULL, &old) == 0 && old.sa_handler == SIG_IGN) continue; /* ignored stays ignored */
    struct sigaction action;
    memset(&action, 0, sizeof action);
    action.sa_handler = forward;
    sigemptyset(&action.sa_mask);
    sigaction(signals[i], &action, NULL);
  }
  got = reply(s, buffer);
  if (got != REPLY_BYTES || buffer[0] != 'X') {
    fprintf(stderr, "fork-shim: the fork server ended before process %d did\n", (int)child);
    kill(child, SIGKILL);
    _exit(255);
  }
  int status;
  memcpy(&value, buffer + 1, sizeof value);
  status = value;
  if (WIFEXITED(status)) _exit(WEXITSTATUS(status));
  if (WIFSIGNALED(status)) {
    int sig = WTERMSIG(status);
    struct rlimit none = {0, 0};
    setrlimit(RLIMIT_CORE, &none);
    signal(sig, SIG_DFL);
    sigset_t only;
    sigemptyset(&only);
    sigaddset(&only, sig);
    sigprocmask(SIG_UNBLOCK, &only, NULL);
    raise(sig);
    _exit(128 + sig);
  }
  _exit(255);
}
