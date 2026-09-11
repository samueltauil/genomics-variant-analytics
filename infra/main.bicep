targetScope = 'subscription'

metadata description = 'Disposable Azure environment for validating the genomics variant accelerator.'

@minLength(2)
@maxLength(10)
@description('Short name distinguishing this environment from any other in the subscription.')
param environmentName string

@description('Region hosting every resource in this environment.')
param location string

@description('Object id of the principal running the deployment. Receives the data-plane roles needed to verify the deployment.')
param deployerPrincipalId string

@minValue(32)
@description('Provisioned size of the SMB landing share, in gibibytes. Task 1.3 writes 100 GiB.')
param landingShareQuotaGiB int = 128

@minValue(3000)
@description('Provisioned IOPS for the landing share. Reported as the share IOPS ceiling.')
param landingProvisionedIops int = 3000

@minValue(125)
@description('Provisioned bandwidth for the landing share, in MiB/s.')
param landingProvisionedBandwidthMibps int = 200

@description('Date this environment is expected to be deleted, as YYYY-MM-DD. Recorded for teardown.')
param expiresOn string

@description('Public key for the verification client. Verification runs through run-command, not SSH.')
param adminPublicKey string

@description('Governance keeps both storage data planes private, so acceptance tests need a client inside the network.')
param deployVerificationClient bool = true

@description('Size of the verification client. Only unrestricted sizes in the target region will deploy.')
param verificationClientSize string = 'Standard_D4s_v7'

param deployedOn string = utcNow('yyyy-MM-ddTHH:mm:ssZ')

var tags = {
  project: 'genomics-variant-accelerator'
  lifecycle: 'disposable-test'
  environment: environmentName
  expiresOn: expiresOn
  deployedOn: deployedOn
}

var suffix = uniqueString(subscription().id, environmentName)

resource environment 'Microsoft.Resources/resourceGroups@2021-04-01' = {
  name: 'rg-genomics-${environmentName}'
  location: location
  tags: tags
}

module identities 'modules/identities.bicep' = {
  scope: environment
  name: 'workload-identities'
  params: {
    location: location
    tags: tags
    suffix: suffix
  }
}

module network 'modules/network.bicep' = {
  scope: environment
  name: 'private-network'
  params: {
    location: location
    tags: tags
    namePrefix: 'genomics-${environmentName}'
  }
}

module landing 'modules/landing-zone.bicep' = {
  scope: environment
  name: 'smb-landing-zone'
  params: {
    location: location
    tags: tags
    storageAccountName: 'stgland${suffix}'
    shareQuotaGiB: landingShareQuotaGiB
    provisionedIops: landingProvisionedIops
    provisionedBandwidthMibps: landingProvisionedBandwidthMibps
    ingestionPrincipalId: identities.outputs.ingestionPrincipalId
    deployerPrincipalId: deployerPrincipalId
  }
}

module lake 'modules/data-lake.bicep' = {
  scope: environment
  name: 'object-storage-landing'
  params: {
    location: location
    tags: tags
    storageAccountName: 'stglake${suffix}'
    stagingPrincipalId: identities.outputs.stagingPrincipalId
    pipelinePrincipalId: identities.outputs.pipelinePrincipalId
    deployerPrincipalId: deployerPrincipalId
  }
}

module landingFileLink 'modules/private-endpoint.bicep' = {
  scope: environment
  name: 'private-link-file'
  params: {
    location: location
    tags: tags
    name: 'pe-${landing.outputs.storageAccountName}-file'
    subnetId: network.outputs.privateEndpointSubnetId
    serviceId: landing.outputs.storageAccountId
    groupId: 'file'
    privateDnsZoneId: network.outputs.fileZoneId
  }
}

module lakeBlobLink 'modules/private-endpoint.bicep' = {
  scope: environment
  name: 'private-link-blob'
  params: {
    location: location
    tags: tags
    name: 'pe-${lake.outputs.storageAccountName}-blob'
    subnetId: network.outputs.privateEndpointSubnetId
    serviceId: lake.outputs.storageAccountId
    groupId: 'blob'
    privateDnsZoneId: network.outputs.blobZoneId
  }
}

module lakeDfsLink 'modules/private-endpoint.bicep' = {
  scope: environment
  name: 'private-link-dfs'
  params: {
    location: location
    tags: tags
    name: 'pe-${lake.outputs.storageAccountName}-dfs'
    subnetId: network.outputs.privateEndpointSubnetId
    serviceId: lake.outputs.storageAccountId
    groupId: 'dfs'
    privateDnsZoneId: network.outputs.dfsZoneId
  }
}

module verificationClient 'modules/test-client.bicep' = if (deployVerificationClient) {
  scope: environment
  name: 'verification-client'
  params: {
    location: location
    tags: tags
    name: 'vm-genomics-${environmentName}'
    subnetId: network.outputs.computeSubnetId
    adminPublicKey: adminPublicKey
    vmSize: verificationClientSize
    userAssignedIdentityIds: identities.outputs.resourceIds
  }
}

module staging 'modules/staging.bicep' = {
  scope: environment
  name: 'staging-pipeline'
  params: {
    location: location
    tags: tags
    name: 'adf-genomics-${environmentName}-${suffix}'
    landingAccountId: landing.outputs.storageAccountId
    landingAccountName: landing.outputs.storageAccountName
    landingShareName: landing.outputs.shareName
    lakeAccountId: lake.outputs.storageAccountId
    lakeAccountName: lake.outputs.storageAccountName
    lakeFilesystem: lake.outputs.filesystemName
    ingestionIdentityId: identities.outputs.ingestionResourceId
    stagingIdentityId: identities.outputs.stagingResourceId
  }
}

output resourceGroupName string = environment.name
output location string = location
output verificationClientName string = deployVerificationClient ? verificationClient!.outputs.clientName : ''
output stagingFactoryName string = staging.outputs.factoryName
output stagingPipelineName string = staging.outputs.pipelineName
output landingStorageAccount string = landing.outputs.storageAccountName
output landingShareName string = landing.outputs.shareName
output landingUncPath string = landing.outputs.uncPath
output lakeStorageAccount string = lake.outputs.storageAccountName
output lakeFilesystem string = lake.outputs.filesystemName
output stagingIdentityClientId string = identities.outputs.stagingClientId
output pipelineIdentityClientId string = identities.outputs.pipelineClientId
output ingestionIdentityClientId string = identities.outputs.ingestionClientId
