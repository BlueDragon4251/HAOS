/* Diskless scope fixture init only. The private marker and PID 1 guard precede
 * all mounts, sockets and UID changes. Use no real disks/network in QEMU. */
#define _GNU_SOURCE
#include <linux/reboot.h>
#include <sys/syscall.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <sys/mount.h>
#include <sys/wait.h>
#include <sys/utsname.h>
#include <unistd.h>
#include <fcntl.h>
#include <stddef.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <errno.h>
static void checked(int ok,const char *stage){
 if(!ok){dprintf(1,"HAOS_SCOPE_FAILURE stage=%s errno=%d\n",stage,errno);_exit(82);}
}
static int listener(const char *name,int abstract){
 int fd=socket(AF_UNIX,SOCK_STREAM|SOCK_CLOEXEC,0);checked(fd>=0,"listener-socket");
 struct sockaddr_un a={.sun_family=AF_UNIX};size_t len=strlen(name);
 checked(len<sizeof(a.sun_path)-1,"listener-length");
 memcpy(a.sun_path+(abstract?1:0),name,len+1);
 checked(bind(fd,(void*)&a,offsetof(struct sockaddr_un,sun_path)+len+1)==0,"listener-bind");
 checked(listen(fd,8)==0,"listener-listen");return fd;
}
int main(void){
 checked(getpid()==1 && getuid()==0,"disposable-init-only");
 int marker=open("/haos-disposable-ipc-marker",O_RDONLY|O_NOFOLLOW|O_NONBLOCK);
 checked(marker>=0,"disposable-marker");struct stat info;checked(fstat(marker,&info)==0,"marker-stat");
 checked(S_ISREG(info.st_mode) && info.st_uid==0 && info.st_nlink==1 && (info.st_mode&0777)==0400,"marker-authority");
 char bytes[64]={0};ssize_t size=read(marker,bytes,sizeof(bytes));close(marker);
 static const char identity[]="haos-scope-disposable-vm-v1\n";
 checked(size==sizeof(identity)-1 && memcmp(bytes,identity,sizeof(identity)-1)==0,"marker-identity");
 struct utsname u;uname(&u);dprintf(1,"HAOS_SCOPE_KERNEL=%s\n",u.release);
 mkdir("/proc",0555);mkdir("/sys",0555);mkdir("/tmp",0777);chmod("/tmp",0777);
 checked(mount("proc","/proc","proc",0,NULL)==0,"private-proc");
 checked(mount("sysfs","/sys","sysfs",0,NULL)==0,"private-sysfs");
 int host=listener("haos-scope-fixture-host",1);
 int named=listener("/tmp/haos-named.sock",0);checked(chmod("/tmp/haos-named.sock",0666)==0,"named-permissions");
 pid_t pid=fork();checked(pid>=0,"fixture-child");
 if(pid==0){
  checked(setgid(1000)==0 && setuid(1000)==0,"fixture-drop-uid");
  execl("/python/bin/python3.11","python3.11","-I","/probe.py",NULL);_exit(83);
 }
 int status;checked(waitpid(pid,&status,0)==pid,"fixture-wait");
 dprintf(1,"HAOS_SCOPE_FINISHED=%d\n",WIFEXITED(status)?WEXITSTATUS(status):255);
 close(host);close(named);sync();
 syscall(SYS_reboot,LINUX_REBOOT_MAGIC1,LINUX_REBOOT_MAGIC2,LINUX_REBOOT_CMD_POWER_OFF,NULL);
 return 1;
}
