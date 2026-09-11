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

var smbShareContributorRoleId = '0c867c2a-1d8c-454a-a3db-ab2ea1bdc8bb'
var smbPrivilegedContributorRoleId = '69566ab7-960f-475b-8e7c-b3118f30c6bd'
var keyOperatorRoleId = '81a9662b-bebf-436f-a333-f67b29880f12'

resource account 'Microsoft.Storage/storageAccounts@2025-01-01' = {
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
    // SMB mounting authenticates with the share key until Entra Kerberos domain join exists.
    allowSharedKeyAccess: true
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

resource ingestionWrite 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, ingestionPrincipalId, smbShareContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', smbShareContributorRoleId)
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

// SMB has no Entra path on a non-domain-joined client, so the ingestion identity retrieves the share
// key itself rather than having it passed in. Task 8.2 removes this once Kerberos exists.
resource ingestionKeyAccess 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, ingestionPrincipalId, keyOperatorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', keyOperatorRoleId)
    principalId: ingestionPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Governance disables shared-key access, so file data-plane verification runs over OAuth.
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
