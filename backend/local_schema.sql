-- 筑维AI 本地库建表脚本（依据后端代码中的 SQL 反推）
CREATE TABLE IF NOT EXISTS `user` (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(50) NOT NULL UNIQUE,
  password VARCHAR(100) DEFAULT '',
  real_name VARCHAR(50) DEFAULT '',
  phone VARCHAR(20) DEFAULT '',
  role VARCHAR(20) DEFAULT 'RESIDENT',
  status TINYINT DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS house (
  id INT AUTO_INCREMENT PRIMARY KEY,
  house_code VARCHAR(30) NOT NULL UNIQUE,
  building_no VARCHAR(30) DEFAULT '',
  unit_no VARCHAR(30) DEFAULT NULL,
  room_no VARCHAR(30) DEFAULT '',
  qr_token VARCHAR(60) DEFAULT '',
  area DECIMAL(8,2) DEFAULT NULL,
  status TINYINT DEFAULT 1,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS house_device (
  id INT AUTO_INCREMENT PRIMARY KEY,
  house_id INT NOT NULL,
  device_code VARCHAR(50) DEFAULT '',
  device_name VARCHAR(100) DEFAULT '',
  device_type VARCHAR(30) DEFAULT '',
  location VARCHAR(100) DEFAULT NULL,
  brand VARCHAR(100) DEFAULT NULL,
  model VARCHAR(100) DEFAULT NULL,
  install_date VARCHAR(30) DEFAULT NULL,
  status VARCHAR(20) DEFAULT 'NORMAL',
  remark VARCHAR(200) DEFAULT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_house (house_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS repair_order (
  id INT AUTO_INCREMENT PRIMARY KEY,
  order_no VARCHAR(50) NOT NULL UNIQUE,
  reporter_id INT DEFAULT NULL,
  house_id INT DEFAULT NULL,
  original_description TEXT,
  ai_summary TEXT,
  repair_category VARCHAR(50) DEFAULT NULL,
  location VARCHAR(100) DEFAULT NULL,
  priority VARCHAR(20) DEFAULT 'NORMAL',
  info_status VARCHAR(30) DEFAULT 'INCOMPLETE',
  status VARCHAR(30) DEFAULT 'DRAFT',
  device_id INT DEFAULT NULL,
  device_description VARCHAR(200) DEFAULT NULL,
  assigned_to INT DEFAULT NULL,
  reviewer_id INT DEFAULT NULL,
  reviewed_at DATETIME DEFAULT NULL,
  completed_at DATETIME DEFAULT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_house (house_id),
  INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS repair_message (
  id INT AUTO_INCREMENT PRIMARY KEY,
  repair_order_id INT DEFAULT NULL,
  sender_id INT DEFAULT NULL,
  sender_type VARCHAR(20) DEFAULT '',
  message_type VARCHAR(30) DEFAULT '',
  content TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_order (repair_order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS repair_record (
  id INT AUTO_INCREMENT PRIMARY KEY,
  repair_order_id INT DEFAULT NULL,
  operator_id INT DEFAULT NULL,
  operator_type VARCHAR(20) DEFAULT '',
  action_type VARCHAR(30) DEFAULT '',
  before_status VARCHAR(30) DEFAULT NULL,
  after_status VARCHAR(30) DEFAULT NULL,
  description TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_order (repair_order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS repair_attachment (
  id INT AUTO_INCREMENT PRIMARY KEY,
  repair_order_id INT DEFAULT NULL,
  uploader_id INT DEFAULT NULL,
  file_name VARCHAR(200) DEFAULT '',
  file_url VARCHAR(500) DEFAULT '',
  file_type VARCHAR(30) DEFAULT '',
  attachment_type VARCHAR(30) DEFAULT '',
  ai_description TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_order (repair_order_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 智能派单：维修人员技能、并发容量与在岗状态。
-- 运行中的旧数据库由 app.services.dispatch_schema 幂等创建并补齐画像。
CREATE TABLE IF NOT EXISTS repairer_profile (
  user_id INT NOT NULL PRIMARY KEY,
  skills TEXT NOT NULL,
  max_active_orders INT NOT NULL DEFAULT 3,
  daily_capacity INT NOT NULL DEFAULT 5,
  on_duty TINYINT NOT NULL DEFAULT 1,
  preferred_buildings VARCHAR(255) DEFAULT '',
  last_assigned_at DATETIME DEFAULT NULL,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  INDEX idx_profile_duty (on_duty)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
