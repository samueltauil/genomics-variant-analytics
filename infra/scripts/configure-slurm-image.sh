#!/usr/bin/env bash
set -Eeuo pipefail
umask 022

required() {
  local name="$1"
  [[ -n "${!name:-}" ]] || { echo "$name is required" >&2; exit 2; }
}

for name in PINNED_KERNEL AMLFS_VERSION AMLFS_PACKAGE_VERSION NEXTFLOW_VERSION \
  NEXTFLOW_SHA256 NEXTFLOW_URL AZCOPY_VERSION AZCOPY_SHA256 AZCOPY_URL \
  REPOSITORY_URL REPOSITORY_COMMIT REPOSITORY_PATH SLURM_PARTITION; do
  required "$name"
done

source /etc/os-release
[[ "$ID" == ubuntu && "$VERSION_ID" == 24.04 ]]
[[ "$(uname -r)" == "$PINNED_KERNEL" ]]
[[ "$REPOSITORY_PATH" == /* && "$REPOSITORY_PATH" != / ]]
[[ "$REPOSITORY_COMMIT" =~ ^[0-9a-f]{40}$ ]]
[[ "$SLURM_PARTITION" =~ ^[A-Za-z0-9._-]+$ ]]

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  ca-certificates curl git gnupg jq mokutil openjdk-17-jre-headless python3 \
  samtools slurm-wlm munge sudo util-linux coreutils findutils

install -d -m 0755 /etc/apt/keyrings
key_file=/tmp/microsoft.asc
curl --fail --location --silent --show-error \
  https://packages.microsoft.com/keys/microsoft.asc --output "$key_file"
key_fingerprint="$(
  gpg --batch --show-keys --with-colons "$key_file" \
    | awk -F: '$1 == "fpr" { print $10; exit }'
)"
[[ "$key_fingerprint" == "BC528686B50D79E339D3721CEB3E94ADBE1229CF" ]]
gpg --batch --dearmor --yes \
  --output /etc/apt/keyrings/microsoft-amlfs.gpg "$key_file"
rm -f "$key_file"
cat >/etc/apt/sources.list.d/amlfs.list <<'EOF'
deb [arch=amd64 signed-by=/etc/apt/keyrings/microsoft-amlfs.gpg] https://packages.microsoft.com/repos/amlfs-noble noble main
EOF
apt-get update

amlfs_package="amlfs-lustre-client-${AMLFS_VERSION}"
kmod_package="kmod-lustre-client-${PINNED_KERNEL}-${AMLFS_VERSION}"
apt-get install -y --no-install-recommends \
  "${amlfs_package}=${AMLFS_PACKAGE_VERSION}" "${kmod_package}=1"
if dpkg-query -W -f='${Status}\n' 'lustre-client-dkms*' 2>/dev/null \
  | grep -q 'install ok installed'; then
  echo "DKMS Lustre package is forbidden" >&2
  exit 20
fi
command -v mount.lustre >/dev/null
[[ "$(modinfo -F vermagic lustre | cut -d ' ' -f 1)" == "$PINNED_KERNEL" ]]
[[ -n "$(modinfo -F signer lustre)" ]]
[[ "$(modinfo -F sig_id lustre)" == "PKCS#7" ]]
! command -v docker >/dev/null
apt-mark hold "$amlfs_package" "$kmod_package" \
  "linux-image-${PINNED_KERNEL}" "linux-modules-${PINNED_KERNEL}"

download_verified() {
  curl --fail --location --silent --show-error "$1" --output "$3"
  echo "$2  $3" | sha256sum -c -
}
download_verified "$NEXTFLOW_URL" "$NEXTFLOW_SHA256" /usr/local/bin/nextflow
chmod 0755 /usr/local/bin/nextflow
NXF_VER="$NEXTFLOW_VERSION" NXF_HOME=/opt/nextflow nextflow -version
download_verified "$AZCOPY_URL" "$AZCOPY_SHA256" /tmp/azcopy.deb
apt-get install -y --no-install-recommends /tmp/azcopy.deb
rm -f /tmp/azcopy.deb
azcopy --version | grep -F "$AZCOPY_VERSION"

rm -rf "$REPOSITORY_PATH"
git clone --filter=blob:none --no-checkout "$REPOSITORY_URL" "$REPOSITORY_PATH"
git -C "$REPOSITORY_PATH" checkout --detach "$REPOSITORY_COMMIT"
[[ "$(git -C "$REPOSITORY_PATH" rev-parse HEAD)" == "$REPOSITORY_COMMIT" ]]
chown -R root:root "$REPOSITORY_PATH"
chmod -R go-w "$REPOSITORY_PATH"

install -d -m 0755 /etc/slurm /etc/munge \
  /var/lib/slurm/slurmctld /var/lib/slurm/slurmd
if [[ ! -s /etc/munge/munge.key ]]; then
  dd if=/dev/urandom of=/etc/munge/munge.key bs=1 count=1024 status=none
fi
chown munge:munge /etc/munge/munge.key
chmod 0400 /etc/munge/munge.key
chown slurm:slurm /var/lib/slurm/slurmctld /var/lib/slurm/slurmd

cat >/usr/local/sbin/configure-local-slurm <<EOF
#!/usr/bin/env bash
set -Eeuo pipefail
host="\$(hostname -s)"
cat >/etc/slurm/slurm.conf <<CONF
ClusterName=genomics-accelerator
SlurmctldHost=\$host
MpiDefault=none
ProctrackType=proctrack/cgroup
ReturnToService=2
SlurmctldPidFile=/run/slurmctld.pid
SlurmdPidFile=/run/slurmd.pid
SlurmdSpoolDir=/var/lib/slurm/slurmd
SlurmUser=slurm
StateSaveLocation=/var/lib/slurm/slurmctld
SwitchType=switch/none
TaskPlugin=task/affinity
SchedulerType=sched/backfill
SelectType=select/cons_tres
SelectTypeParameters=CR_Core
NodeName=\$host CPUs=1 State=UNKNOWN
PartitionName=$SLURM_PARTITION Nodes=\$host Default=YES MaxTime=INFINITE State=UP
CONF
EOF
chmod 0755 /usr/local/sbin/configure-local-slurm

cat >/etc/systemd/system/genomics-slurm-config.service <<'EOF'
[Unit]
Description=Configure single-node Slurm for the current host name
Before=slurmctld.service slurmd.service
After=network.target
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/configure-local-slurm
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
EOF
for service in slurmctld slurmd; do
  install -d -m 0755 "/etc/systemd/system/${service}.service.d"
  cat >"/etc/systemd/system/${service}.service.d/genomics.conf" <<'EOF'
[Unit]
Requires=genomics-slurm-config.service munge.service
After=genomics-slurm-config.service munge.service
EOF
done

cat >/etc/sudoers.d/azureuser-amlfs <<'EOF'
azureuser ALL=(ALL) NOPASSWD: ALL
EOF
chmod 0440 /etc/sudoers.d/azureuser-amlfs
visudo -cf /etc/sudoers.d/azureuser-amlfs
systemctl daemon-reload
systemctl enable genomics-slurm-config.service munge.service \
  slurmctld.service slurmd.service walinuxagent.service

install -d -m 0755 /etc/genomics-variant-accelerator
jq -n \
  --arg kernel "$PINNED_KERNEL" --arg amlfs "$AMLFS_VERSION" \
  --arg amlfsPackageVersion "$AMLFS_PACKAGE_VERSION" \
  --arg nextflow "$NEXTFLOW_VERSION" --arg azcopy "$AZCOPY_VERSION" \
  --arg repositoryUrl "$REPOSITORY_URL" \
  --arg repositoryCommit "$REPOSITORY_COMMIT" \
  --arg repositoryPath "$REPOSITORY_PATH" \
  --arg slurmPartition "$SLURM_PARTITION" \
  '{schema_version:1,os:"Canonical Ubuntu 24.04 LTS Gen2",
    security_type:"TrustedLaunchSupported",secure_boot_required:true,
    vtpm_required:true,kernel:$kernel,amlfs_client:$amlfs,
    amlfs_install_method:"prebuilt-kmod",
    amlfs_package_version:$amlfsPackageVersion,nextflow:$nextflow,
    azcopy:$azcopy,repository_url:$repositoryUrl,
    repository_commit:$repositoryCommit,repository_path:$repositoryPath,
    slurm_partition:$slurmPartition}' \
  >/etc/genomics-variant-accelerator/image-manifest.json

apt-get clean
rm -rf /var/lib/apt/lists/* /tmp/*
