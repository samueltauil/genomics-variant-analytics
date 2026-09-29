targetScope = 'resourceGroup'

param location string
param environment string
param buildId string
param stagingResourceGroupId string
param galleryResourceGroupName string
param galleryName string
param imageDefinitionName string
param galleryImageVersion string
param sourceImageVersion string
param sourceKernel string
param amlfsVersion string
param amlfsPackageVersion string
param nextflowVersion string
param nextflowSha256 string
param nextflowUrl string
param azcopyVersion string
param azcopySha256 string
param azcopyUrl string
param repositoryUrl string
param repositoryCommit string
param repositoryPath string = '/opt/genomics-variant-analytics'
param slurmPartition string = 'debug'
param buildVmSize string = 'Standard_D4s_v7'
param deployImageTemplate bool = true
param buildSubnetPrefix string = '10.44.0.0/24'

var tags = {
  project: 'genomics-variant-accelerator'
  component: 'hpc-image-build'
  environment: environment
  buildId: buildId
  lifecycle: 'ephemeral'
}
var imageTags = {
  project: 'genomics-variant-accelerator'
  component: 'private-slurm-image'
  environment: environment
  buildId: buildId
  sourceImage: 'Canonical:ubuntu-24_04-lts:server:${sourceImageVersion}'
  sourceKernel: sourceKernel
  amlfsClient: amlfsVersion
  amlfsInstall: 'prebuilt-kmod'
  secureBoot: 'required'
  vtpm: 'required'
  repositoryCommit: repositoryCommit
  repositoryPath: repositoryPath
  slurmPartition: slurmPartition
}

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: 'id-aib-${buildId}'
  location: location
  tags: tags
}

resource nsg 'Microsoft.Network/networkSecurityGroups@2024-05-01' = {
  name: 'nsg-aib-${buildId}'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'DenyInternetInbound'
        properties: {
          priority: 4096
          direction: 'Inbound'
          access: 'Deny'
          protocol: '*'
          sourceAddressPrefix: 'Internet'
          sourcePortRange: '*'
          destinationAddressPrefix: '*'
          destinationPortRange: '*'
        }
      }
    ]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-aib-${buildId}'
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        '10.44.0.0/16'
      ]
    }
    subnets: [
      {
        name: 'snet-build'
        properties: {
          addressPrefix: buildSubnetPrefix
          defaultOutboundAccess: true
          privateLinkServiceNetworkPolicies: 'Disabled'
          networkSecurityGroup: {
            id: nsg.id
          }
        }
      }
    ]
  }
}

resource galleryDefinition 'Microsoft.Compute/galleries/images@2024-03-03' existing = {
  name: '${galleryName}/${imageDefinitionName}'
  scope: resourceGroup(galleryResourceGroupName)
}

resource networkContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(vnet.id, identity.id, 'network-contributor')
  scope: vnet
  properties: {
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '4d97b98b-1d4f-4787-a291-c67834d212e7'
    )
  }
}

var configureScript = loadFileAsBase64('scripts/configure-slurm-image.sh')

resource template 'Microsoft.VirtualMachineImages/imageTemplates@2024-02-01' = if (deployImageTemplate) {
  name: 'aib-${buildId}'
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity.id}': {}
    }
  }
  properties: {
    buildTimeoutInMinutes: 120
    stagingResourceGroup: stagingResourceGroupId
    source: {
      type: 'PlatformImage'
      publisher: 'Canonical'
      offer: 'ubuntu-24_04-lts'
      sku: 'server'
      version: sourceImageVersion
    }
    vmProfile: {
      vmSize: buildVmSize
      osDiskSizeGB: 64
      vnetConfig: {
        subnetId: vnet.properties.subnets[0].id
      }
    }
    customize: [
      {
        type: 'Shell'
        name: 'configure-private-slurm'
        inline: [
          'echo ${configureScript} | base64 -d >/tmp/configure-slurm-image.sh'
          'chmod 0700 /tmp/configure-slurm-image.sh'
          'PINNED_KERNEL=${sourceKernel} AMLFS_VERSION=${amlfsVersion} AMLFS_PACKAGE_VERSION=${amlfsPackageVersion} NEXTFLOW_VERSION=${nextflowVersion} NEXTFLOW_SHA256=${nextflowSha256} NEXTFLOW_URL=${nextflowUrl} AZCOPY_VERSION=${azcopyVersion} AZCOPY_SHA256=${azcopySha256} AZCOPY_URL=${azcopyUrl} REPOSITORY_URL=${repositoryUrl} REPOSITORY_COMMIT=${repositoryCommit} REPOSITORY_PATH=${repositoryPath} SLURM_PARTITION=${slurmPartition} /tmp/configure-slurm-image.sh'
        ]
      }
    ]
    validate: {
      continueDistributeOnFailure: false
      sourceValidationOnly: false
      inVMValidations: [
        {
          type: 'Shell'
          name: 'validate-image-interface'
          inline: [
            'test "$(uname -r)" = "${sourceKernel}"'
            'test -n "$(modinfo -F signer lustre)"'
            'test "$(modinfo -F sig_id lustre)" = "PKCS#7"'
            'test "$(modinfo -F vermagic lustre | cut -d " " -f 1)" = "${sourceKernel}"'
            'command -v mount.lustre && command -v azcopy && command -v java && command -v nextflow && command -v python3 && command -v samtools'
            'command -v mount && command -v mountpoint && command -v findmnt && command -v sha256sum && command -v find && command -v sort && command -v xargs'
            'test -d "${repositoryPath}/workflows"'
            'grep -Fq "SLURM_LUSTRE_WORKDIR is required" "${repositoryPath}/workflows/conf/slurm.config"'
            'grep -Fq "docker.enabled = false" "${repositoryPath}/workflows/conf/slurm.config"'
            '! grep -Fq "AZURE_BATCH_ACR_LOGIN_SERVER" "${repositoryPath}/workflows/conf/slurm.config"'
            'grep -Fq -- "--reference-manifest-sha256" "${repositoryPath}/scripts/run_nextflow_secondary_pipeline.py"'
            'test ! -d /var/lib/dkms/lustre-client'
            '! command -v docker >/dev/null'
          ]
        }
      ]
    }
    distribute: [
      {
        type: 'SharedImage'
        galleryImageId: '${galleryDefinition.id}/versions/${galleryImageVersion}'
        runOutputName: 'slurm-${galleryImageVersion}'
        artifactTags: imageTags
        replicationRegions: [
          location
        ]
        storageAccountType: 'Standard_LRS'
      }
    ]
  }
  dependsOn: [
    networkContributor
  ]
}

output imageTemplateId string = deployImageTemplate ? template.id : ''
output imageTemplateName string = 'aib-${buildId}'
output identityId string = identity.id
output vnetId string = vnet.id
output buildSubnetId string = vnet.properties.subnets[0].id
output galleryImageVersionId string = '${galleryDefinition.id}/versions/${galleryImageVersion}'
