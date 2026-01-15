#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <errno.h>
#include <arpa/inet.h>
#include <sys/socket.h>

int main() {
    int sock;
    struct sockaddr_in servaddr;
    char buf[64];

    sock = socket(AF_INET, SOCK_STREAM, 0);

    servaddr.sin_family = AF_INET;
    servaddr.sin_port = htons(8080);
    inet_pton(AF_INET, "127.0.0.1", &servaddr.sin_addr);

    if (connect(sock, (struct sockaddr *)&servaddr, sizeof(servaddr)) < 0) {
        perror("connect failed");
        return 1;
    }

    const char *req =
        "GET / HTTP/1.1\r\n"
        "Host: localhost\r\n"
        "\r\n";

    write(sock, req, strlen(req));

    while (1) {
        ssize_t n = read(sock, buf, sizeof(buf));
        if (n > 0) {
            fwrite(buf, 1, n, stdout);
        } else if (n == 0) {
            printf("\nserver closed connection\n");
            break;
        } else {
            perror("\nerror reading from socket");
            break;
        }
    }

    close(sock);
    return 0;
}