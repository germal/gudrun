#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_LSM303_U.h>
#include <Adafruit_L3GD20_U.h>
#include <Adafruit_9DOF.h>


/* Assign a unique ID to the sensors */
Adafruit_9DOF                 dof   = Adafruit_9DOF();
Adafruit_LSM303_Accel_Unified accel = Adafruit_LSM303_Accel_Unified(30301);
Adafruit_LSM303_Mag_Unified   mag   = Adafruit_LSM303_Mag_Unified(30302);
Adafruit_L3GD20_Unified       gyro  = Adafruit_L3GD20_Unified(30303);


void initSensors() {
  if(!accel.begin())
  {
    /* There was a problem detecting the LSM303 ... check your connections */
    while(1) {
      Serial.println(F("Ooops, no accel detected ... Check your wiring!"));
      delay(1000);
    }
  }
  if(!mag.begin())
  {
    /* There was a problem detecting the LSM303 ... check your connections */
    while(1) {
      Serial.println("Ooops, no mag detected ... Check your wiring!");
      delay(1000);
    }
  }
  if(!gyro.begin())
  {
    while(1) {
      Serial.println("Oops, no gyro detected ... Check your wiring!");
      delay(1000);
    }
  }
}


void setup(void) {
  Serial.begin(115200);
  initSensors();
}

// Since turning this on increases the number of bytes sent,
// it should match what the receiver expects.
//
// However, note that it also makes the loop() here about 33% slower.
#define DO_FUSION 0

void loop(void) {

  sensors_event_t accel_event;
  sensors_event_t mag_event;
  sensors_event_t gyro_event;
  sensors_vec_t   orientation;


  typedef struct {
    //    acceleration, gyro,         magnetometer  
    float ax, ay, az,   gx, gy, gz,   mx, my, mz;
    #if DO_FUSION==1
      // "orientation"
      flot roll, pitch, heading;
    #endif
  } DataPackage;
  DataPackage package;

  if(
    accel.getEvent(&accel_event)
    && 
    mag.getEvent(&mag_event)
    && 
    gyro.getEvent(&gyro_event)
    #if DO_FUSION==1
      &&
      dof.fusionGetOrientation(&accel_event, &mag_event, &orientation)
    #endif
    ) {

    package.ax = accel_event.acceleration.x;
    package.ay = accel_event.acceleration.y;
    package.az = accel_event.acceleration.z;

    package.gx = gyro_event.gyro.x;
    package.gy = gyro_event.gyro.y;
    package.gz = gyro_event.gyro.z;

    package.mx = mag_event.magnetic.x;
    package.my = mag_event.magnetic.y;
    package.mz = mag_event.magnetic.z;

    #if DO_FUSION==1
      package.roll = orientation.roll;
      package.pitch = orientation.pitch;
      package.heading = orientation.heading;
    #endif

    Serial.write('S');
    Serial.write((byte*)&package, sizeof(package));
    Serial.write('E');
  }
}
