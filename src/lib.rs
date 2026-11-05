#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EditorBuffer {
    pub file_path: String,
    pub line_count: usize,
    pub modified: bool,
}

impl EditorBuffer {
    pub fn open(path: &str, lines: usize) -> Self {
        Self { file_path: path.into(), line_count: lines, modified: false }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn test_editor_buffer_aaa() {
        // Arrange & Act
        let buf = EditorBuffer::open("/etc/hosts", 12);
        // Assert
        assert_eq!(buf.file_path, "/etc/hosts");
        assert_eq!(buf.line_count, 12);
        assert!(!buf.modified);
    }
}
