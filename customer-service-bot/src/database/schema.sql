-- Customer Service Bot Database Schema
-- MySQL 8.0+

CREATE DATABASE IF NOT EXISTS customer_service
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE customer_service;

-- ─── Orders ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS orders (
    order_id VARCHAR(50) PRIMARY KEY,
    platform VARCHAR(20) NOT NULL,
    customer_id VARCHAR(50) NOT NULL,
    customer_name VARCHAR(100),
    customer_phone VARCHAR(20),
    status VARCHAR(30) NOT NULL,
    status_display VARCHAR(20),
    total_amount DECIMAL(10, 2) DEFAULT 0,
    shipping_fee DECIMAL(10, 2) DEFAULT 0,
    discount DECIMAL(10, 2) DEFAULT 0,
    payment_method VARCHAR(30),
    shipping_address JSON,
    timeline JSON,
    created_at DATETIME,
    paid_at DATETIME,
    shipped_at DATETIME,
    delivered_at DATETIME,
    INDEX idx_customer_id (customer_id),
    INDEX idx_customer_phone (customer_phone),
    INDEX idx_platform (platform),
    INDEX idx_status (status)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS order_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    order_id VARCHAR(50) NOT NULL,
    sku VARCHAR(50),
    base_product_id VARCHAR(50),
    name VARCHAR(200),
    color VARCHAR(30),
    size VARCHAR(10),
    price DECIMAL(10, 2),
    quantity INT DEFAULT 1,
    FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE CASCADE,
    INDEX idx_order_id (order_id)
) ENGINE=InnoDB;

-- ─── Products ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS products (
    base_product_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(200) NOT NULL,
    category VARCHAR(50),
    subcategory VARCHAR(50),
    brand VARCHAR(100),
    description TEXT,
    specs JSON,
    available_sizes JSON,
    available_colors JSON,
    images JSON,
    is_returnable BOOLEAN DEFAULT TRUE,
    returnable_category VARCHAR(50),
    tags_attached_by_default BOOLEAN DEFAULT TRUE,
    returnable_condition VARCHAR(50),
    created_at DATE,
    INDEX idx_category (category),
    INDEX idx_brand (brand)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS product_variants (
    id INT AUTO_INCREMENT PRIMARY KEY,
    base_product_id VARCHAR(50) NOT NULL,
    sku VARCHAR(50) NOT NULL,
    color VARCHAR(30),
    size VARCHAR(10),
    price DECIMAL(10, 2),
    stock INT DEFAULT 0,
    FOREIGN KEY (base_product_id) REFERENCES products(base_product_id) ON DELETE CASCADE,
    UNIQUE KEY uk_sku (sku),
    INDEX idx_product_id (base_product_id)
) ENGINE=InnoDB;

-- ─── Logistics ───────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS logistics (
    tracking_no VARCHAR(50) PRIMARY KEY,
    order_id VARCHAR(50),
    company VARCHAR(50),
    company_code VARCHAR(20),
    status VARCHAR(30),
    current_location VARCHAR(200),
    estimated_delivery DATE,
    origin VARCHAR(100),
    destination VARCHAR(200),
    tracking_history JSON,
    signed_by VARCHAR(50),
    signed_time DATETIME,
    FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE SET NULL,
    INDEX idx_order_id (order_id)
) ENGINE=InnoDB;

-- ─── Refunds ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS refunds (
    refund_id VARCHAR(50) PRIMARY KEY,
    order_id VARCHAR(50),
    status VARCHAR(30),
    status_display VARCHAR(20),
    amount DECIMAL(10, 2),
    reason VARCHAR(200),
    type VARCHAR(30),
    applied_at DATETIME,
    stages JSON,
    refund_channel VARCHAR(50),
    expected_completion DATE,
    FOREIGN KEY (order_id) REFERENCES orders(order_id) ON DELETE SET NULL,
    INDEX idx_order_id (order_id)
) ENGINE=InnoDB;

-- ─── FAQ ─────────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS faq (
    id VARCHAR(20) PRIMARY KEY,
    question VARCHAR(500) NOT NULL,
    answer TEXT NOT NULL,
    category VARCHAR(50),
    tags JSON,
    INDEX idx_category (category)
) ENGINE=InnoDB;

-- ─── Policies ────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS policies (
    id INT AUTO_INCREMENT PRIMARY KEY,
    policy_name VARCHAR(100),
    version VARCHAR(20),
    effective_date DATE,
    rules JSON,
    auto_review_threshold DECIMAL(10, 2),
    return_address JSON,
    non_returnable_categories JSON,
    supported_couriers JSON,
    default_courier VARCHAR(50)
) ENGINE=InnoDB;

-- ─── Tickets ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS tickets (
    ticket_id VARCHAR(50) PRIMARY KEY,
    type VARCHAR(50),
    status VARCHAR(20) DEFAULT 'pending',
    created_at DATETIME,
    resolved_at DATETIME,
    order_id VARCHAR(50),
    customer_id VARCHAR(50),
    customer_name VARCHAR(100),
    customer_phone VARCHAR(20),
    platform VARCHAR(20),
    order_amount DECIMAL(10, 2),
    order_status VARCHAR(30),
    order_created DATETIME,
    item JSON,
    return_reason VARCHAR(200),
    return_description TEXT,
    product_info JSON,
    expected_response VARCHAR(50),
    assigned_to VARCHAR(50),
    resolution VARCHAR(50),
    resolved_note TEXT,
    INDEX idx_status (status),
    INDEX idx_order_id (order_id)
) ENGINE=InnoDB;

-- ─── Memory ──────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS memory_interactions (
    id VARCHAR(50) PRIMARY KEY,
    customer_id VARCHAR(50) NOT NULL,
    thread_id VARCHAR(100),
    user_message TEXT,
    assistant_message TEXT,
    metadata JSON,
    timestamp DATETIME,
    INDEX idx_customer_id (customer_id),
    INDEX idx_thread_id (thread_id),
    INDEX idx_timestamp (timestamp)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS customer_profiles (
    customer_id VARCHAR(50) PRIMARY KEY,
    profile JSON,
    updated_at DATETIME
) ENGINE=InnoDB;