metadata description = 'SSD provisioned v2 SMB landing zone for unchanged sequencer output (tasks 1.3, 2.4).'

param location string
param tags object

@minLength(3)
@maxLength(24)
param storageAccountName string

param shareName string = 'landing'
param shareQuotaGiB int
param provisionedIops int
param provisionedBandwidthMibps int
param ingestionPrincipalId string
param deployerPrincipalId string

@description('Private endpoints replace this in task 8.7; until then the share is reachable for acceptance testing.')
param allowPublicNetworkAccess bool = true

var smbManagedIdentityAdminRoleId = 'a235d3ee-5935-4cfb-8cc5-a3303ad5995e'
var smbPrivilegedContributorRoleId = '69566ab7-960f-475b-8e7c-b3118f30c6bd'

resource account 'Microsoft.Storage/storageAccounts@2025-08-01' = {
  name: storageAccountName
  location: location
  tags: tags
  sku: {
    name: 'PremiumV2_LRS'
  }
  kind: 'FileStorage'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    // Clients authenticate SMB with a managed identity, so no share key exists to mount with.
    azureFilesIdentityBasedAuthentication: {
      directoryServiceOptions: 'None'
      smbOAuthSettings: {
        isSmbOAuthEnabled: true
      }
    }
    publicNetworkAccess: allowPublicNetworkAccess ? 'Enabled' : 'Disabled'
    networkAcls: {
      bypass: 'AzureServices'
      defaultAction: allowPublicNetworkAccess ? 'Allow' : 'Deny'
    }
  }
}

resource fileServices 'Microsoft.Storage/storageAccounts/fileServices@2025-01-01' = {
  parent: account
  name: 'default'
  properties: {
    protocolSettings: {
      smb: {
        versions: 'SMB3.1.1'
        authenticationMethods: 'NTLMv2;Kerberos'
        kerberosTicketEncryption: 'AES-256'
        channelEncryption: 'AES-128-GCM;AES-256-GCM'
        multichannel: {
          enabled: true
        }
      }
    }
  }
}

resource share 'Microsoft.Storage/storageAccounts/fileServices/shares@2025-01-01' = {
  parent: fileServices
  name: shareName
  properties: {
    enabledProtocols: 'SMB'
    shareQuota: shareQuotaGiB
    provisionedIops: provisionedIops
    provisionedBandwidthMibps: provisionedBandwidthMibps
  }
}

resource ingestionSmbAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, ingestionPrincipalId, smbManagedIdentityAdminRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', smbManagedIdentityAdminRoleId)
    principalId: ingestionPrincipalId
    principalType: 'ServicePrincipal'
  }
}

resource deployerVerify 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, deployerPrincipalId, smbPrivilegedContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', smbPrivilegedContributorRoleId)
    principalId: deployerPrincipalId
  }
}

// Data Factory reads the share over the file REST data plane with this identity.
resource ingestionFileData 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, ingestionPrincipalId, smbPrivilegedContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', smbPrivilegedContributorRoleId)
    principalId: ingestionPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output storageAccountName string = account.name
output storageAccountId string = account.id
output shareName string = share.name
output uncPath string = '//${account.name}.file.${az.environment().suffixes.storage}/${share.name}'
