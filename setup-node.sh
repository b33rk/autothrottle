set -ex

# add Docker repository
curl -fsSL https://download.docker.com/linux/ubuntu/gpg >/usr/share/keyrings/docker.asc
echo 'deb [arch=amd64 signed-by=/usr/share/keyrings/docker.asc] https://download.docker.com/linux/ubuntu focal stable' >/etc/apt/sources.list.d/docker.list

# add Kubernetes repository
curl -fsSL https://pkgs.k8s.io/core:/stable:/v1.28/deb/Release.key -o /usr/share/keyrings/kubernetes.asc
echo 'deb [signed-by=/usr/share/keyrings/kubernetes.asc] https://pkgs.k8s.io/core:/stable:/v1.28/deb/ /' >/etc/apt/sources.list.d/kubernetes.list

# install Docker
apt-get update
apt-get install -y containerd.io docker-ce=5:19.03.15~3-0~ubuntu-focal docker-ce-cli=5:19.03.15~3-0~ubuntu-focal
apt-mark hold docker-ce docker-ce-cli

# setup Docker
echo '{"exec-opts":["native.cgroupdriver=systemd"],"log-driver":"json-file","log-opts":{"max-size":"100m"},"storage-driver":"overlay2"}' >/etc/docker/daemon.json
systemctl restart docker

# install Kubernetes
apt-get install -y kubeadm=1.28.* kubectl=1.28.* kubelet=1.28.*
apt-mark hold kubeadm kubectl kubelet

if [ "$1" = master ]; then
    # initialize Kubernetes cluster
    kubeadm init --pod-network-cidr=10.244.0.0/16

    # setup Kubernetes credentials
    mkdir -p .kube
    cp /etc/kubernetes/admin.conf .kube/config

    # setup Kubernetes networking
    kubectl apply -f flannel.yaml

    # save join command and credentials
    kubeadm token create --print-join-command >join-command
    cp .kube/config kube-config

    # install Python dependencies
    apt-get install -y python3-venv
    python3 -m venv venv
    venv/bin/pip install -r requirements.txt

    # make Locust available globally
    ln -s /root/venv/bin/locust /usr/local/bin/locust

elif [ "$1" = worker ]; then
    # join Kubernetes cluster
    bash join-command

    # setup Kubernetes credentials
    mkdir -p .kube
    cp kube-config .kube/config

    # run worker daemon in background
    tmux new-session -d './worker-daemon.py'
fi
