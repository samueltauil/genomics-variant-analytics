metadata description = 'Ephemeral Azure Managed Lustre filesystem with Blob HSM integration.'

param location string
param tags object

@minLength(2)
@maxLength(80)
param name string

param subnetId string
param dataContainerId string = ''
param loggingContainerId string = ''
param skuName string = 'AMLFS-Durable-Premium-500'

@minValue(4)
param storageCapacityTiB int = 4

param maintenanceDayOfWeek string = 'Saturday'
param maintenanceTimeUtc string = '22:00'
param zone string = '1'

var filesystemProperties = empty(dataContainerId) || empty(loggingContainerId) ? {
  filesystemSubnet: subnetId
  storageCapacityTiB: storageCapacityTiB
  maintenanceWindow: {
    dayOfWeek: maintenanceDayOfWeek
    timeOfDayUTC: maintenanceTimeUtc
  }
} : {
  filesystemSubnet: subnetId
  storageCapacityTiB: storageCapacityTiB
  hsm: {
    settings: {
      container: dataContainerId
      loggingContainer: loggingContainerId
    }
  }
  maintenanceWindow: {
    dayOfWeek: maintenanceDayOfWeek
    timeOfDayUTC: maintenanceTimeUtc
  }
}

resource filesystem 'Microsoft.StorageCache/amlFilesystems@2026-01-01' = {
  name: name
  location: location
  zones: [
    zone
  ]
  sku: {
    name: skuName
  }
  tags: tags
  properties: filesystemProperties
}

output filesystemId string = filesystem.id
output filesystemName string = filesystem.name
